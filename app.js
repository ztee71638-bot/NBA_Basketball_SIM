const $ = (id) => document.getElementById(id);
let games = [];
let players = [];
let teamData = [];
let selectedGame = null;
let selectedPlayer = null;
let selectedPlayerLogs = [];
const fmt = (n) => Number(n).toFixed(1) + "%";
async function loadJson(path) {
  const response = await fetch(path + "?v=" + Date.now(), {cache:"no-store"});
  if (!response.ok) throw new Error(path + " returned HTTP " + response.status);
  return response.json();
}
function showGames() {
  const root = $("games");
  if (!games.length) { root.innerHTML = '<p class="muted">No games found in the current three-day feed.</p>'; return; }
  root.innerHTML = games.map((g,i) => {
    const away = g.away?.name || "Away team", home = g.home?.name || "Home team";
    const score = g.completed || g.status === "STATUS_IN_PROGRESS" ? ` · ${g.away?.score ?? "–"}–${g.home?.score ?? "–"}` : "";
    return `<div class="game"><div><strong>${away} @ ${home}</strong><small>${new Date(g.date).toLocaleString()} · ${g.status_detail || g.status || "Scheduled"}${score}</small></div><button data-game="${i}">Simulate</button></div>`;
  }).join("");
  root.querySelectorAll("[data-game]").forEach(b=>b.addEventListener("click",()=>selectGame(games[Number(b.dataset.game)])));
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
function selectGame(game) {
  selectedGame = game;
  $("selected-title").textContent = game.name || game.short_name || "Selected matchup";
  $("game-results").textContent = "Matchup selected. Review the starting estimates and run the simulation.";
  prefillGameProjections(game);
}
function normalSample(mean, sd) {
  let u=0,v=0; while(!u)u=Math.random(); while(!v)v=Math.random();
  return mean + sd * Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);
}
function runGameSimulation() {
  if (!selectedGame) { $("game-results").textContent="Select a matchup first."; return; }
  const hm=Number($("home-mean").value), am=Number($("away-mean").value), sd=Number($("score-sd").value);
  const trials=Math.min(100000,Math.max(1000,Number($("trials").value)||10000));
  if (![hm,am,sd].every(Number.isFinite) || sd<=0) { $("game-results").textContent="Enter valid projections and a positive standard deviation."; return; }
  let hw=0,aw=0,homeTotal=0,awayTotal=0,totals=[];
  for(let i=0;i<trials;i++){let h=Math.max(50,Math.round(normalSample(hm,sd))),a=Math.max(50,Math.round(normalSample(am,sd)));if(h>a)hw++;else if(a>h)aw++;homeTotal+=h;awayTotal+=a;totals.push(h+a);}
  totals.sort((a,b)=>a-b);
  $("game-results").innerHTML=`<div class="result-grid"><div class="metric"><small>Home win</small><b>${fmt(hw/trials*100)}</b></div><div class="metric"><small>Away win</small><b>${fmt(aw/trials*100)}</b></div><div class="metric"><small>Avg. home score</small><b>${(homeTotal/trials).toFixed(1)}</b></div><div class="metric"><small>Avg. away score</small><b>${(awayTotal/trials).toFixed(1)}</b></div><div class="metric"><small>Median total</small><b>${totals[Math.floor(trials*.5)]}</b></div></div><p class="fine-print">${trials.toLocaleString()} trials. Independent normal score assumptions; starting means may use recent team scoring and points-allowed averages, but lineups, injuries, pace and score correlation are not yet modeled. Not a calibrated betting recommendation.</p>`;
}
function erf(x){const sign=x<0?-1:1;x=Math.abs(x);const t=1/(1+0.3275911*x);const y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);return sign*y;}
function calcProp(){
  const mean=Number($("prop-mean").value),sd=Number($("prop-sd").value),line=Number($("prop-line").value);
  if(![mean,sd,line].every(Number.isFinite)||sd<=0){$("prop-results").textContent="Enter valid values and a positive standard deviation.";return;}
  const over=(1-erf((line-mean)/(sd*Math.sqrt(2))))/2;
  $("prop-results").innerHTML=`<div class="result-grid"><div class="metric"><small>Over probability</small><b>${fmt(over*100)}</b></div><div class="metric"><small>Under probability</small><b>${fmt((1-over)*100)}</b></div></div><p class="fine-print">Normal-distribution estimate from your inputs only. No player history, minutes, matchup, injury or market adjustment is included.</p>`;
}
async function loadMarkets(){
  try{const data=await loadJson("data/polymarket.json");const rows=data.markets||[];$("markets").innerHTML=rows.length?rows.slice(0,40).map(m=>`<div class="market"><div><strong>${m.question||"Untitled market"}</strong><small>24h volume: ${m.volume_24h??"n/a"} · Liquidity: ${m.liquidity??"n/a"}</small></div>${m.url?'<a target="_blank" rel="noopener" href="'+m.url+'">Open market</a>':""}</div>`).join(""):'<p class="muted">No likely NBA markets found in the latest public market snapshot.</p>';}catch(e){$("markets").textContent="Market feed unavailable: "+e.message;}
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
function renderPlayerSearch() {
  const root = $("player-search-results");
  const query = ($("player-search").value || "").trim().toLowerCase();
  const matches = players.filter(p => !query || [p.name,p.team,p.position].some(v => String(v || "").toLowerCase().includes(query))).slice(0,20);
  if (!players.length) { root.innerHTML = '<p class="muted">Player history has not been loaded yet.</p>'; return; }
  if (!matches.length) { root.innerHTML = '<p class="muted">No players match that search.</p>'; return; }
  root.innerHTML = matches.map(p => '<div class="game"><div><strong>' + escapeHtml(p.name) + '</strong><small>' + escapeHtml(p.team) + ' · ' + escapeHtml(p.position || "Position n/a") + ' · ' + escapeHtml(p.status) + '</small></div><button data-player-id="' + escapeHtml(p.id) + '">View history</button></div>').join("");
  root.querySelectorAll("[data-player-id]").forEach(b => b.addEventListener("click", () => showPlayer(b.dataset.playerId)));
}
function applyPlayerHistoricalBaseline() {
  if (!selectedPlayer || !selectedPlayerLogs.length) {
    $("prop-source-status").textContent = "No game-log sample is available for the selected player.";
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
  $("prop-source-status").textContent = selectedPlayer.name + " · " + stat.toUpperCase() +
    " historical baseline from " + values.length + " recent games. This is not adjusted for minutes, role, injuries, opponent or expected game script.";
}

function showPlayer(playerId) {
  const p = players.find(item => String(item.id) === String(playerId));
  if (!p) return;
  const seasons = Object.entries(p.seasons || {}).sort((a,b) => Number(b[0])-Number(a[0]));
  const chosen = seasons.find(([,logs]) => logs && logs.length) || seasons[0];
  if (!chosen || !chosen[1]?.length) {
    $("player-detail").textContent = p.name + ": roster record found, but no game logs were returned for the stored seasons.";
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
  $("player-detail").innerHTML = '<h3>' + escapeHtml(p.name) + ' · ' + escapeHtml(p.team) + ' · Season ' + escapeHtml(season) + '</h3><div class="result-grid"><div class="metric"><small>Last 10 PTS avg</small><b>' + avg("points") + '</b></div><div class="metric"><small>Last 10 REB avg</small><b>' + avg("rebounds") + '</b></div><div class="metric"><small>Last 10 AST avg</small><b>' + avg("assists") + '</b></div></div><div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th></tr></thead><tbody>' + rows + '</tbody></table></div><p class="fine-print">Last 10 averages use available numeric game logs only. Historical logs are descriptive, not projections.</p>';
}
async function loadTeams() {
  try {
    const data = await loadJson("data/teams.json");
    teamData = data.teams || [];
    if (data.last_updated) $("data-status").textContent += " · Teams updated " + new Date(data.last_updated).toLocaleString();
  } catch (e) {
    teamData = [];
  }
}
async function loadPlayers() {
  try {
    const data = await loadJson("data/players.json");
    players = data.players || [];
    renderPlayerSearch();
    if (data.last_updated) $("data-status").textContent += " · Players updated " + new Date(data.last_updated).toLocaleString();
  } catch (e) {
    $("player-search-results").textContent = "Player database unavailable: " + e.message;
  }
}

async function loadAll(){
  try{const data=await loadJson("data/games.json");games=data.games||[];$("data-status").textContent="ESPN updated "+(data.last_updated?new Date(data.last_updated).toLocaleString():"time unavailable");showGames();}catch(e){$("data-status").textContent="Game feed unavailable";$("games").textContent=e.message;}
  await loadPlayers();
  await loadTeams();
  await loadMarkets();
}
$("simulate").addEventListener("click",runGameSimulation);
$("prop-calc").addEventListener("click",calcProp);
$("prop-stat").addEventListener("change",applyPlayerHistoricalBaseline);
$("reload").addEventListener("click",loadAll);
$("player-search").addEventListener("input",renderPlayerSearch);
loadAll();
