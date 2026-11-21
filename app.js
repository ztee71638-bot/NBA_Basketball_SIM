const $ = (id) => document.getElementById(id);
let games = [];
let players = [];
let teamData = [];
let injuryData = [];
let marketData = [];
let selectedPropMarket = null;
let selectedGame = null;
let selectedPlayer = null;
let selectedPlayerLogs = [];
const fmt = (n) => Number(n).toFixed(1) + "%";
async function loadJson(path) {
  const response = await fetch(path + "?v=" + Date.now(), {cache:"no-store"});
  if (!response.ok) throw new Error(path + " returned HTTP " + response.status);
  return response.json();
}
let scheduleDays = [];
let activeScheduleDay = 0;
function showGames() {
  const root = $("games");
  if (!games.length) { root.innerHTML = '<p class="muted">No games found in the current feed.</p>'; $("day-label").textContent = "No games scheduled"; return; }
  const grouped = new Map();
  games.forEach((game,index) => {
    const date = new Date(game.date);
    const key = Number.isNaN(date.getTime()) ? "unknown" : date.toLocaleDateString("en-CA");
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push({game,index});
  });
  scheduleDays = [...grouped.entries()].sort((a,b)=>a[0].localeCompare(b[0]));
  activeScheduleDay = Math.min(activeScheduleDay, scheduleDays.length-1);
  root.innerHTML = scheduleDays.map(([key,items],dayIndex) => {
    const label = key === "unknown" ? "Date unavailable" : new Date(items[0].game.date).toLocaleDateString(undefined,{weekday:"long",month:"long",day:"numeric"});
    return '<section class="day-page" data-day-index="'+dayIndex+'"><div class="day-page-heading"><strong>'+escapeHtml(label)+'</strong><span>'+items.length+' '+(items.length===1?'game':'games')+'</span></div>'+
      items.map(({game,index}) => {
        const away=game.away?.name||"Away team",home=game.home?.name||"Home team";
        const score=game.completed||game.status==="STATUS_IN_PROGRESS"?' · '+(game.away?.score??"–")+'–'+(game.home?.score??"–"):"";
        return '<div class="game"><div><strong>'+escapeHtml(away)+' @ '+escapeHtml(home)+'</strong><small>'+escapeHtml(new Date(game.date).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}))+' · '+escapeHtml(game.status_detail||game.status||"Scheduled")+escapeHtml(score)+'</small></div><button data-game="'+index+'">Simulate 100K</button></div>';
      }).join("")+'</section>';
  }).join("");
  root.querySelectorAll("[data-game]").forEach(button=>button.addEventListener("click",()=>{
    selectGame(games[Number(button.dataset.game)]);
    runGameSimulation();
    $("selected-title").scrollIntoView({behavior:"smooth",block:"start"});
  }));
  updateDayNavigation();
}
function updateDayNavigation() {
  const label=$("day-label");
  const current=scheduleDays[activeScheduleDay];
  if(label&&current){
    const first=current[1][0].game.date;
    label.textContent=new Date(first).toLocaleDateString(undefined,{weekday:"long",month:"short",day:"numeric"})+' · '+(activeScheduleDay+1)+' of '+scheduleDays.length;
  }
  $("day-prev").disabled=activeScheduleDay<=0;
  $("day-next").disabled=activeScheduleDay>=scheduleDays.length-1;
  const page=$("games").querySelector('[data-day-index="'+activeScheduleDay+'"]');
  if(page) page.scrollIntoView({behavior:"smooth",block:"nearest",inline:"start"});
}
function canonicalTeam(abbr) {
  const aliases = {GS:"GSW",NY:"NYK",NO:"NOP",SA:"SAS",WSH:"WAS",UTAH:"UTA"};
  return aliases[abbr] || abbr;
}
function teamSummary(abbr) {
  const key = canonicalTeam(abbr);
  const team = teamData.find(t => t.abbreviation === key);
  if (!team) return null;
  const seasons = Object.entries(team.seasons || {}).sort((a,b)=>Number(b[0])-Number(a[0]));
  const season = seasons.find(([,value]) => (value.summary?.games || 0) >= 5);
  return season ? {year:season[0], ...season[1].summary} : null;
}
function prefillGameProjections(game) {
  const home = teamSummary(game.home?.abbreviation);
  const away = teamSummary(game.away?.abbreviation);
  const fields = [home?.last10_avg_points_for, home?.last10_avg_points_against, away?.last10_avg_points_for, away?.last10_avg_points_against];
  if (fields.every(v => Number.isFinite(v))) {
    const homeMean = (home.last10_avg_points_for + away.last10_avg_points_against) / 2 + 1.5;
    const awayMean = (away.last10_avg_points_for + home.last10_avg_points_against) / 2 - 1.5;
    $("home-mean").value = homeMean.toFixed(1);
    $("away-mean").value = awayMean.toFixed(1);
    $("projection-status").textContent = "Starting estimates use last-10 scoring and points-allowed averages (" + home.year + "/" + away.year + "). They still omit confirmed lineups, injuries, pace and matchup adjustments.";
  } else {
    $("projection-status").textContent = "Team history is unavailable or too limited for this matchup. The score inputs remain manual assumptions.";
  }
}
function teamMarketTokens(team) {
  const name = String(team?.name || "").toLowerCase();
  const parts = name.split(/\s+/).filter(Boolean);
  return [name, parts.slice(-2).join(" "), parts.slice(-1).join(" "), String(team?.abbreviation || "").toLowerCase()]
    .filter(value => value.length >= 3);
}
function renderGameMarkets(game) {
  const root = $("game-market-info");
  if (!marketData.length) {
    root.textContent = "Polymarket markets are still loading.";
    return;
  }
  const awayTokens = teamMarketTokens(game.away);
  const homeTokens = teamMarketTokens(game.home);
  const matches = marketData.filter(market => {
    const eventText = String(market.event_title || market.question || market.slug || "").toLowerCase();
    return awayTokens.some(token => eventText.includes(token)) && homeTokens.some(token => eventText.includes(token));
  }).slice(0,8);
  if (!matches.length) {
    root.textContent = "No matching active Polymarket event was found for this ESPN matchup.";
    return;
  }
  root.innerHTML = '<strong>Matching Polymarket markets</strong>' + matches.map(market =>
    '<div class="market"><div><strong>' + escapeHtml(market.question || market.event_title) +
    '</strong><small>' + escapeHtml(market.market_type || "market") + " · " + escapeHtml(marketPriceSummary(market) || "Prices unavailable") +
    ' · 24h volume: ' + escapeHtml(market.volume_24h ?? "n/a") + '</small></div>' +
    (market.url ? '<a target="_blank" rel="noopener" href="' + escapeHtml(market.url) + '">Open market</a>' : '') +
    '</div>'
  ).join("");
}

function selectGame(game) {
  selectedGame = game;
  $("selected-title").textContent = game.name || game.short_name || "Selected matchup";
  $("game-results").textContent = "Matchup selected. Review the starting estimates and run the simulation.";
  prefillGameProjections(game);
  renderGameMarkets(game);
}
function normalSample(mean, sd) {
  let u=0,v=0; while(!u)u=Math.random(); while(!v)v=Math.random();
  return mean + sd * Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);
}
function runGameSimulation() {
  if (!selectedGame) { $("game-results").textContent="Select a matchup first."; return; }
  const hm=Number($("home-mean").value), am=Number($("away-mean").value), sd=Number($("score-sd").value);
  const trials=100000;
  if (![hm,am,sd].every(Number.isFinite) || sd<=0) { $("game-results").textContent="Enter valid projections and a positive standard deviation."; return; }
  let hw=0,aw=0,homeTotal=0,awayTotal=0,totals=[];
  for(let i=0;i<trials;i++){let h=Math.max(50,Math.round(normalSample(hm,sd))),a=Math.max(50,Math.round(normalSample(am,sd)));if(h>a)hw++;else if(a>h)aw++;homeTotal+=h;awayTotal+=a;totals.push(h+a);}
  totals.sort((a,b)=>a-b);
  $("game-results").innerHTML=`<div class="result-grid"><div class="metric"><small>Home win</small><b>${fmt(hw/trials*100)}</b></div><div class="metric"><small>Away win</small><b>${fmt(aw/trials*100)}</b></div><div class="metric"><small>Avg. home score</small><b>${(homeTotal/trials).toFixed(1)}</b></div><div class="metric"><small>Avg. away score</small><b>${(awayTotal/trials).toFixed(1)}</b></div><div class="metric"><small>Median total</small><b>${totals[Math.floor(trials*.5)]}</b></div></div><p class="fine-print">${trials.toLocaleString()} trials. Independent normal score assumptions; starting means may use recent team scoring and points-allowed averages, but lineups, injuries, pace and score correlation are not yet modeled. Not a calibrated betting recommendation.</p>`;
}
function erf(x){const sign=x<0?-1:1;x=Math.abs(x);const t=1/(1+0.3275911*x);const y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);return sign*y;}
function calcProp(){
  const mean=Number($("prop-mean").value),sd=Number($("prop-sd").value),line=Number($("prop-line").value);
  if(selectedPlayer){
    const injury=injuryData.find(item=>String(item.athlete_id)===String(selectedPlayer.id));
    const status=String(injury?.status||"").toLowerCase();
    if(injury && ["out","doubtful","questionable","day-to-day"].some(flag=>status.includes(flag))){
      $("prop-results").textContent="PASS — ESPN lists "+selectedPlayer.name+" as "+injury.status+". Do not use the historical baseline as an active-player projection.";
      return;
    }
    const stat=$("prop-stat").value;
    const statSample=selectedPlayerLogs.map(game=>game[stat]).filter(Number.isFinite);
    if(statSample.length<5){
      $("prop-results").textContent="PASS — only "+statSample.length+" usable recent "+stat+" results are available for "+selectedPlayer.name+"; at least 5 are required.";
      return;
    }
    const minuteSample=selectedPlayerLogs.map(game=>game.minutes).filter(Number.isFinite);
    if(minuteSample.length<5){
      $("prop-results").textContent="PASS — fewer than 5 recent minutes records are available for "+selectedPlayer.name+".";
      return;
    }
    const avgMinutes=minuteSample.reduce((sum,value)=>sum+value,0)/minuteSample.length;
    const minuteVariance=minuteSample.reduce((sum,value)=>sum+Math.pow(value-avgMinutes,2),0)/Math.max(1,minuteSample.length-1);
    if(avgMinutes<15||Math.sqrt(minuteVariance)>8){
      $("prop-results").textContent="PASS — "+selectedPlayer.name+" has an unstable or limited recent minutes role (average "+avgMinutes.toFixed(1)+" minutes; variability "+Math.sqrt(minuteVariance).toFixed(1)+").";
      return;
    }
  }
  if(![mean,sd,line].every(Number.isFinite)||sd<=0){$("prop-results").textContent="Enter valid values and a positive standard deviation.";return;}
  const over=(1-erf((line-mean)/(sd*Math.sqrt(2))))/2;
  let marketComparison = "";
  if(selectedPropMarket){
    const prices=parseMarketArray(selectedPropMarket.outcome_prices);
    const outcomes=parseMarketArray(selectedPropMarket.outcomes);
    let marketOver=Number(prices[0]);
    const firstOutcome=String(outcomes[0]||"").toLowerCase();
    if(firstOutcome.includes("under")||firstOutcome==="no") marketOver=1-marketOver;
    if(Number.isFinite(marketOver)){
      marketComparison='<p class="fine-print">Polymarket implied Over: '+fmt(marketOver*100)+'. Historical baseline difference: '+(over*100-marketOver*100).toFixed(1)+' percentage points. This is an uncalibrated comparison, not a validated betting edge.</p>';
    }
  }
  $("prop-results").innerHTML=`<div class="result-grid"><div class="metric"><small>Over probability</small><b>${fmt(over*100)}</b></div><div class="metric"><small>Under probability</small><b>${fmt((1-over)*100)}</b></div></div><p class="fine-print">Normal-distribution estimate from recent history or manual assumptions. Minutes, role, matchup and game-script adjustments are not included.</p>`+marketComparison;
}
function parseMarketArray(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") return Object.values(value);
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }
  return [];
}
function marketPriceSummary(market) {
  const outcomes = parseMarketArray(market.outcomes);
  const prices = parseMarketArray(market.outcome_prices);
  if (!prices.length) return "";
  return outcomes.map((outcome, index) => {
    const price = Number(prices[index]);
    return Number.isFinite(price) ? escapeHtml(outcome) + " " + Math.round(price * 100) + "¢" : "";
  }).filter(Boolean).join(" · ");
}

async function loadMarkets(){
  try{const data=await loadJson("data/polymarket.json");const rows=data.markets||[];marketData=rows;$("data-status").textContent += " · Polymarket " + rows.length + " markets";$("markets").innerHTML=rows.length?rows.slice(0,40).map(m=>`<div class="market"><div><strong>${escapeHtml(m.question||"Untitled market")}</strong><small>${m.market_type ? escapeHtml(m.market_type.replace("_"," ")) + " · " : ""}${marketPriceSummary(m) ? marketPriceSummary(m) + " · " : ""}24h volume: ${m.volume_24h??"n/a"} · Liquidity: ${m.liquidity??"n/a"}</small></div>${m.url?'<a target="_blank" rel="noopener" href="'+escapeHtml(m.url)+'">Open market</a>':""}</div>`).join(""):'<p class="muted">No likely NBA markets found in the latest public market snapshot.</p>';}catch(e){marketData=[];$("markets").textContent="Market feed unavailable: "+e.message;}
  if(selectedGame) renderGameMarkets(selectedGame);
  if(selectedPlayer) renderPlayerMarkets(selectedPlayer);
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
function renderPlayerSearch() {
  const root = $("player-search-results");
  const query = ($("player-search").value || "").trim().toLowerCase();
  if (!query) {
    root.innerHTML = "";
    return;
  }
  if (!players.length) { root.innerHTML = '<p class="muted">Player history has not been loaded yet.</p>'; return; }
  const matches = players.filter(p => [p.name,p.team,p.position].some(v => String(v || "").toLowerCase().includes(query))).slice(0,20);
  if (!matches.length) { root.innerHTML = '<p class="muted">No players match that search.</p>'; return; }
  root.innerHTML = matches.map(p => {
    const injury = injuryData.find(item => String(item.athlete_id) === String(p.id));
    const availability = injury ? " · Injury: " + (injury.status || "listed") : "";
    const gameCount = Object.values(p.seasons || {}).reduce((sum, logs) => sum + (Array.isArray(logs) ? logs.length : 0), 0);
    return '<div class="game"><div><strong>' + escapeHtml(p.name) + '</strong><small>' + escapeHtml(p.team) + ' · ' + escapeHtml(p.position || "Position n/a") + ' · ' + escapeHtml(p.status) + ' · ' + gameCount + ' game logs' + escapeHtml(availability) + '</small></div><button data-player-id="' + escapeHtml(p.id) + '">View history</button></div>';
  }).join("");
  root.querySelectorAll("[data-player-id]").forEach(b => b.addEventListener("click", () => showPlayer(b.dataset.playerId)));
}
function applyPlayerHistoricalBaseline() {
  if (!selectedPlayer || !selectedPlayerLogs.length) {
    $("prop-source-status").textContent = selectedPlayer
      ? "No game-log sample is available for " + selectedPlayer.name + "."
      : "Select a player below to load a historical baseline, or enter assumptions manually.";
    return;
  }
  const stat = $("prop-stat").value;
  const values = selectedPlayerLogs.map(g => g[stat]).filter(v => Number.isFinite(v));
  if (!values.length) {
    $("prop-source-status").textContent = "No " + stat + " values were found in the latest available game logs for " + selectedPlayer.name + ".";
    return;
  }
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.length > 1
    ? values.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) / (values.length - 1)
    : 1;
  $("prop-mean").value = mean.toFixed(1);
  $("prop-sd").value = Math.max(1, Math.sqrt(variance)).toFixed(1);
  const injury = injuryData.find(item => String(item.athlete_id) === String(selectedPlayer.id));
  const injuryWarning = injury
    ? " ESPN injury report: " + (injury.status || "status unspecified") + (injury.type ? " (" + injury.type + ")" : "") + "."
    : "";
  $("prop-source-status").textContent = selectedPlayer.name + " · " + stat.toUpperCase() +
    " historical baseline from " + values.length + " recent games. This is not adjusted for minutes, role, injuries, opponent or expected game script." + injuryWarning;
}

function renderPlayerMarkets(player) {
  const root = $("player-market-matches");
  if (!root || !player) return;
  const playerName = String(player.name || "").toLowerCase();
  const matches = marketData.filter(market =>
    [market.question, market.market_group, market.slug].join(" ").toLowerCase().includes(playerName)
  ).slice(0,10);
  if (!matches.length) {
    root.innerHTML = '<p class="muted">No matching Polymarket player-prop markets found in the current NBA game-market snapshot.</p>';
    return;
  }
  root.innerHTML = '<h4>Matching Polymarket player markets</h4>' + matches.map(market =>
    '<div class="market"><div><strong>' + escapeHtml(market.question) +
    '</strong><small>' + escapeHtml(market.market_type || "player prop") + " · " + escapeHtml(marketPriceSummary(market) || "Prices unavailable") +
    ' · 24h volume: ' + escapeHtml(market.volume_24h ?? "n/a") + '</small></div>' +
    '<button data-simulate-prop="' + escapeHtml(market.id) + '">Simulate prop</button>' +
    (market.url ? '<a target="_blank" rel="noopener" href="' + escapeHtml(market.url) + '">Open market</a>' : '') +
    '</div>'
  ).join("");
  root.querySelectorAll("[data-simulate-prop]").forEach(button =>
    button.addEventListener("click", () => simulatePlayerMarket(button.dataset.simulateProp))
  );
}

function simulatePlayerMarket(marketId) {
  const market = marketData.find(item => String(item.id) === String(marketId));
  if (!market || !selectedPlayer) return;
  const description = [market.market_group, market.question, market.slug].join(" ").toLowerCase();
  const statMap = [
    ["points", "points"], ["rebounds", "rebounds"], ["assists", "assists"],
    ["steals", "steals"], ["blocks", "blocks"]
  ];
  const statMatches = statMap.filter(([label]) => description.includes(label));
  const match = statMatches.length === 1 ? statMatches[0] : null;
  const lineMatch = description.match(/(?:o\/u|over|under)\s*([0-9]+(?:\.[0-9]+)?)/i) ||
    description.match(/([0-9]+(?:\.[0-9]+)?)\s*$/);
  if (!match || !lineMatch) {
    $("prop-results").textContent = "This Polymarket market could not be mapped to a supported player stat and line yet.";
    return;
  }
  selectedPropMarket = market;
  $("prop-stat").value = match[1];
  $("prop-line").value = lineMatch[1];
  applyPlayerHistoricalBaseline();
  calcProp();
}


function showPlayer(playerId) {
  const p = players.find(item => String(item.id) === String(playerId));
  if (!p) return;
  $("player-detail").hidden = false;
  selectedPlayer = p;
  selectedPlayerLogs = [];
  selectedPropMarket = null;
  const seasons = Object.entries(p.seasons || {}).sort((a,b) => Number(b[0])-Number(a[0]));
  const chosen = seasons.find(([,logs]) => logs && logs.length) || seasons[0];
  if (!chosen || !chosen[1]?.length) {
    $("player-detail").innerHTML = escapeHtml(p.name) + ": roster record found, but no game logs were returned for the stored seasons.<div id=\'player-market-matches\'></div>";
    applyPlayerHistoricalBaseline();
    renderPlayerMarkets(p);
    return;
  }
  const season = chosen[0], logs = chosen[1];
  const sortedLogs = [...logs].sort((a,b) => new Date(b.date || 0) - new Date(a.date || 0));
  const recent = sortedLogs.slice(0,10);
  selectedPlayer = p;
  selectedPlayerLogs = recent;
  applyPlayerHistoricalBaseline();
  const avg = key => {
    const vals = recent.map(g=>g[key]).filter(v=>Number.isFinite(v));
    return vals.length ? (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1) : "n/a";
  };
  const rows = sortedLogs.slice(0,15).map(g => '<tr><td>' + escapeHtml(g.date ? new Date(g.date).toLocaleDateString() : "—") + '</td><td>' + escapeHtml(g.opponent || "—") + '</td><td>' + escapeHtml(g.result || "—") + '</td><td>' + (g.minutes ?? "—") + '</td><td>' + (g.points ?? "—") + '</td><td>' + (g.rebounds ?? "—") + '</td><td>' + (g.assists ?? "—") + '</td></tr>').join("");
  $("player-detail").innerHTML = '<h3>' + escapeHtml(p.name) + ' · ' + escapeHtml(p.team) + ' · Season ' + escapeHtml(season) + '</h3><div class="result-grid"><div class="metric"><small>Last 10 PTS avg</small><b>' + avg("points") + '</b></div><div class="metric"><small>Last 10 REB avg</small><b>' + avg("rebounds") + '</b></div><div class="metric"><small>Last 10 AST avg</small><b>' + avg("assists") + '</b></div></div><div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th></tr></thead><tbody>' + rows + '</tbody></table></div><p class="fine-print">Last 10 averages use available numeric game logs only. Historical logs are descriptive, not projections.</p><div id="player-market-matches"></div>';
  renderPlayerMarkets(p);
}
function renderInjuries() {
  const root = $("injuries");
  if (!injuryData.length) {
    root.innerHTML = '<p class="muted">No injury records are currently listed by ESPN.</p>';
    return;
  }

  // Show a compact list of teams first. Player rows stay hidden until a
  // team heading is tapped, so the full injury list never expands by default.
  const byTeam = new Map();
  injuryData.forEach(item => {
    const teamCode = String(item.team || "UNK").trim();
    const teamName = String(item.team_name || teamCode).trim();
    if (!byTeam.has(teamCode)) byTeam.set(teamCode, { name: teamName, players: [] });
    byTeam.get(teamCode).players.push(item);
  });

  const teams = [...byTeam.entries()].sort((a,b) => a[1].name.localeCompare(b[1].name));
  root.innerHTML = '<div class="injury-overview"><strong>' + teams.length +
    ' teams with injuries</strong><span>' + injuryData.length + ' players</span></div>' +
    teams.map(([code, group], index) => {
      const rows = group.players.map(item => {
        const status = item.status || "Status not specified";
        const detail = [item.type, item.side].filter(Boolean).join(" · ");
        const comment = item.short_comment || item.long_comment || "";
        const returnDate = item.return_date ? " · Return: " + escapeHtml(item.return_date) : "";
        return '<div class="injury-player"><div class="injury-player-main"><strong>' +
          escapeHtml(item.name || "Player not specified") + '</strong><span class="injury-status">' +
          escapeHtml(status) + '</span></div>' +
          (detail || returnDate ? '<small>' + escapeHtml(detail) + escapeHtml(returnDate) + '</small>' : '') +
          (comment ? '<p>' + escapeHtml(comment) + '</p>' : '') + '</div>';
      }).join("");
      return '<section class="injury-team"><button type="button" class="injury-team-toggle" data-injury-team="' +
        index + '" aria-expanded="false" aria-controls="injury-team-panel-' + index + '">' +
        '<span class="injury-team-name">' + escapeHtml(group.name) + '</span>' +
        '<span class="injury-team-count">' + group.players.length + '</span><span class="injury-chevron">＋</span></button>' +
        '<div class="injury-team-players" id="injury-team-panel-' + index + '" hidden>' + rows + '</div></section>';
    }).join("");

  root.querySelectorAll("[data-injury-team]").forEach(button => {
    button.addEventListener("click", () => {
      const panel = $(button.getAttribute("aria-controls").replace("injury-team-panel-", "injury-team-panel-"));
      const opening = button.getAttribute("aria-expanded") !== "true";
      // Keep the report tidy: only one team's players are expanded at a time.
      root.querySelectorAll(".injury-team-toggle").forEach(other => {
        const otherPanel = document.getElementById(other.getAttribute("aria-controls"));
        other.setAttribute("aria-expanded", "false");
        other.querySelector(".injury-chevron").textContent = "＋";
        if (otherPanel) otherPanel.hidden = true;
      });
      if (opening) {
        button.setAttribute("aria-expanded", "true");
        button.querySelector(".injury-chevron").textContent = "−";
        panel.hidden = false;
      }
    });
  });
}

async function loadInjuries() {
  try {
    const data = await loadJson("data/injuries.json");
    injuryData = data.injuries || [];
    renderInjuries();
    renderPlayerSearch();
    if (selectedPlayer) applyPlayerHistoricalBaseline();
    if (data.last_updated) $("data-status").textContent += " · Injuries " + injuryData.length + " updated " + new Date(data.last_updated).toLocaleString();
  } catch (e) {
    $("injuries").textContent = "Injury report unavailable: " + e.message;
  }
}

async function loadTeams() {
  try {
    const data = await loadJson("data/teams.json");
    teamData = data.teams || [];
    if (data.last_updated) $("data-status").textContent += " · Teams " + teamData.length + " updated " + new Date(data.last_updated).toLocaleString();
  } catch (e) {
    teamData = [];
  }
}
async function loadPlayers() {
  try {
    const data = await loadJson("data/players.json");
    players = data.players || [];
    renderPlayerSearch();
    if (data.last_updated) $("data-status").textContent += " · Players " + players.length + " updated " + new Date(data.last_updated).toLocaleString();
  } catch (e) {
    $("player-search-results").textContent = "Player database unavailable: " + e.message;
  }
}

async function loadAll(){
  try{const data=await loadJson("data/games.json");games=data.games||[];$("data-status").textContent="ESPN updated "+(data.last_updated?new Date(data.last_updated).toLocaleString():"time unavailable");showGames();}catch(e){$("data-status").textContent="Game feed unavailable";$("games").textContent=e.message;}
  await loadPlayers();
  await loadTeams();
  await loadInjuries();
  await loadMarkets();
}
$("simulate").addEventListener("click",runGameSimulation);
$("day-prev").addEventListener("click",()=>{activeScheduleDay=Math.max(0,activeScheduleDay-1);updateDayNavigation();});
$("day-next").addEventListener("click",()=>{activeScheduleDay=Math.min(scheduleDays.length-1,activeScheduleDay+1);updateDayNavigation();});
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{
  document.querySelectorAll("[data-view]").forEach(tab=>{const active=tab===button;tab.classList.toggle("active",active);tab.setAttribute("aria-selected",String(active));});
  document.querySelectorAll(".view-panel").forEach(panel=>panel.hidden=panel.id!==button.dataset.view);
}));
$("prop-calc").addEventListener("click",calcProp);
$("prop-stat").addEventListener("change",()=>{selectedPropMarket=null;applyPlayerHistoricalBaseline();});
$("prop-line").addEventListener("input",()=>{selectedPropMarket=null;});
$("reload").addEventListener("click",loadAll);
$("player-search").addEventListener("input",renderPlayerSearch);
loadAll();
