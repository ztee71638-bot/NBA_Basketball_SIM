const $ = (id) => document.getElementById(id);
let games = [];
let players = [];
let playerImpactData = [];
let playerImpactLoaded = false;
let playerImpactLoading = null;
let playersLoaded = false;
let playersLoading = null;
let teamData = [];
let teamUpdatedAt = null;
let arenaData = {};
let playerUpdatedAt = null;
let injuryData = [];
let injuryUpdatedAt = null;
let lineupData = [];
let lineupsUpdatedAt = null;
let marketData = [];
let marketsLoaded = false;
let marketsLoading = null;
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
        return '<article class="game matchup-card"><div class="matchup-main"><div class="matchup-teams">'+teamLogoMarkup(game.away,"away")+'<span class="matchup-at">@</span>'+teamLogoMarkup(game.home,"home")+'</div><small class="matchup-time">'+escapeHtml(new Date(game.date).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}))+' · '+escapeHtml(game.status_detail||game.status||"Scheduled")+escapeHtml(score)+'</small></div><button class="run-simulation-btn" data-game="'+index+'"><span class="play-icon">▶</span>Run Simulation</button></article>';
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
const TEAM_NAMES = {ATL:'Atlanta Hawks',BOS:'Boston Celtics',BKN:'Brooklyn Nets',CHA:'Charlotte Hornets',CHI:'Chicago Bulls',CLE:'Cleveland Cavaliers',DAL:'Dallas Mavericks',DEN:'Denver Nuggets',DET:'Detroit Pistons',GSW:'Golden State Warriors',HOU:'Houston Rockets',IND:'Indiana Pacers',LAC:'LA Clippers',LAL:'Los Angeles Lakers',MEM:'Memphis Grizzlies',MIA:'Miami Heat',MIL:'Milwaukee Bucks',MIN:'Minnesota Timberwolves',NOP:'New Orleans Pelicans',NYK:'New York Knicks',OKC:'Oklahoma City Thunder',ORL:'Orlando Magic',PHI:'Philadelphia 76ers',PHX:'Phoenix Suns',POR:'Portland Trail Blazers',SAC:'Sacramento Kings',SAS:'San Antonio Spurs',TOR:'Toronto Raptors',UTA:'Utah Jazz',WAS:'Washington Wizards'};
function teamDisplayName(abbr) { return TEAM_NAMES[canonicalTeam(abbr)] || String(abbr || 'NBA Team'); }
const TEAM_COLORS = {
 ATL:["#C8102E","#FDB927"],BOS:["#007A33","#BA9653"],BKN:["#000000","#FFFFFF"],CHA:["#1D1160","#00788C"],CHI:["#CE1141","#000000"],
 CLE:["#6F263D","#FFB81C"],DAL:["#00538C","#B8C4CA"],DEN:["#0E2240","#FEC524"],DET:["#C8102E","#1D42BA"],GSW:["#1D428A","#FFC72C"],
 HOU:["#CE1141","#000000"],IND:["#002D62","#FDBB30"],LAC:["#C8102E","#1D428A"],LAL:["#552583","#FDB927"],MEM:["#5D76A9","#12173F"],
 MIA:["#98002E","#F9A01B"],MIL:["#00471B","#EEE1C6"],MIN:["#0C2340","#236192"],NOP:["#0C2340","#C8102E"],NYK:["#006BB6","#F58426"],
 OKC:["#007AC1","#EF3B24"],ORL:["#0077C0","#C4CED4"],PHI:["#006BB6","#ED174C"],PHX:["#1D1160","#E56020"],POR:["#E03A3E","#000000"],
 SAC:["#5A2D81","#63727A"],SAS:["#C4CED4","#000000"],TOR:["#CE1141","#000000"],UTA:["#002B5C","#F9A01B"],WAS:["#002B5C","#E31837"]
};
function teamColorStyle(team) {
 const abbr=canonicalTeam(team?.abbreviation||team?.abbr||"");
 const colors=TEAM_COLORS[abbr]||["#167f78","#20e0d0"];
 return "--team-primary:"+colors[0]+";--team-secondary:"+colors[1];
}
function teamLogoUrl(team) {
  const abbr = canonicalTeam(team?.abbreviation || team?.abbr || "");
  return abbr ? "https://a.espncdn.com/i/teamlogos/nba/500/"+encodeURIComponent(abbr)+".png" : "";
}
function teamLogoMarkup(team, side) {
  const name = team?.name || teamDisplayName(team?.abbreviation);
  const url = teamLogoUrl(team);
  return '<span class="team-brand '+side+'">'+(url?'<img class="team-logo" src="'+escapeHtml(url)+'" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">':'<span class="team-logo-fallback">'+escapeHtml((team?.abbreviation||name||"NBA").slice(0,3))+'</span>')+'<span class="team-brand-name">'+escapeHtml(name)+'</span></span>';
}

function showTeam(abbreviation) {
  const team = teamData.find(item => canonicalTeam(item.abbreviation) === canonicalTeam(abbreviation));
  const root = $("team-detail"); if (!root || !team) return;
  $("player-detail").hidden = true;
  const seasons = Object.entries(team.seasons || {}).sort((a,b) => Number(b[0])-Number(a[0]));
  const selected = seasons.find(([,data]) => (data.games || []).length) || seasons[0];
  if (!selected) { root.hidden=false; root.textContent='No historical team records are available.'; return; }
  const season=selected[0], data=selected[1], s=data.summary||{};
  const games=[...(data.games||[])].sort((a,b)=>new Date(b.date||0)-new Date(a.date||0));
  const pct=v=>Number.isFinite(v)?(v*100).toFixed(1)+'%':'—';
  const num=v=>Number.isFinite(v)?Number(v).toFixed(1):'—';
  const rows=games.map(g=>'<tr><td>'+escapeHtml(g.date?new Date(g.date).toLocaleDateString():'—')+'</td><td>'+escapeHtml(g.opponent_name||g.opponent||'—')+'</td><td>'+escapeHtml(g.home_away||'—')+'</td><td>'+escapeHtml(g.result||'—')+'</td><td>'+num(g.points_for)+'</td><td>'+num(g.points_against)+'</td><td>'+num(Number.isFinite(g.points_for)&&Number.isFinite(g.points_against)?g.points_for-g.points_against:NaN)+'</td></tr>').join('');
  root.hidden=false;
  root.innerHTML='<div class="section-head"><div><p class="eyebrow">TEAM HISTORY</p><h3>'+escapeHtml(teamDisplayName(team.abbreviation))+' · '+escapeHtml(team.abbreviation)+'</h3></div><span class="muted">Season '+escapeHtml(season)+'</span></div>'+
  '<div class="result-grid">'+
  '<div class="metric"><small>Record</small><b>'+Number(s.wins||0)+'-'+Math.max(0,Number(s.games||0)-Number(s.wins||0))+'</b></div>'+
  '<div class="metric"><small>Win rate</small><b>'+pct(s.win_pct)+'</b></div>'+
  '<div class="metric"><small>Points scored / game</small><b>'+num(s.avg_points_for)+'</b></div>'+
  '<div class="metric"><small>Points allowed / game</small><b>'+num(s.avg_points_against)+'</b></div>'+
  '<div class="metric"><small>Last 10 record</small><b>'+Number(s.last10_wins||0)+'-'+Math.max(0,Number(s.last10_games||0)-Number(s.last10_wins||0))+'</b></div>'+
  '<div class="metric"><small>Last 10 win rate</small><b>'+pct(s.last10_win_pct)+'</b></div>'+
  '<div class="metric"><small>Last 10 points scored</small><b>'+num(s.last10_avg_points_for)+'</b></div>'+
  '<div class="metric"><small>Last 10 points allowed</small><b>'+num(s.last10_avg_points_against)+'</b></div></div>'+
  '<h4>Game-by-game history ('+games.length+')</h4><div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Opponent</th><th>Venue</th><th>Result</th><th>PF</th><th>PA</th><th>+/-</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
  '<p class="fine-print">Historical ESPN team schedule records. Advanced team metrics are not included in this data source.</p>';
}

function teamSummary(abbr) {
  const key = canonicalTeam(abbr);
  const team = teamData.find(t => t.abbreviation === key);
  if (!team) return null;
  const seasons = Object.entries(team.seasons || {}).sort((a,b)=>Number(b[0])-Number(a[0]));
  const season = seasons.find(([,value]) => (value.summary?.games || 0) >= 5);
  return season ? {year:season[0], ...season[1].summary} : null;
}
function teamSeasonGames(abbreviation) {
  const team = teamData.find(item => canonicalTeam(item.abbreviation) === canonicalTeam(abbreviation));
  if (!team) return {rows:[],year:null};
  const seasons = Object.entries(team.seasons || {}).sort((a,b) => Number(a[0])-Number(b[0]));
  const populated = seasons.filter(([,value]) => (value.games || []).length > 0);
  if (!populated.length) return {rows:[],year:null};
  const latest = populated[populated.length-1];
  // Keep a short tail from the prior season as an early-season prior, while
  // retaining even the first few games of the active season.
  const previous = populated.length>1 ? populated[populated.length-2][1].games.slice(-10) : [];
  const current = latest[1].games || [];
  const rows = [...previous,...current]
    .filter(g => Number.isFinite(g.points_for) && Number.isFinite(g.points_against) && g.points_for>0 && g.points_against>0)
    .sort((a,b)=>new Date(a.date)-new Date(b.date));
  return {rows,year:latest[0],previousSeasonGames:previous.length};
}
function weightedMetric(rows, key, halfLife=8) {
  const values = rows.map((row,index) => ({value:Number(row[key]), age:rows.length-1-index}))
    .filter(item => Number.isFinite(item.value));
  if (!values.length) return null;
  let totalWeight=0, squaredWeight=0, weighted=0;
  values.forEach(item=>{const w=Math.pow(0.5,item.age/halfLife);totalWeight+=w;squaredWeight+=w*w;weighted+=item.value*w;});
  const mean=weighted/totalWeight;
  let variance=0;
  values.forEach(item=>{const w=Math.pow(0.5,item.age/halfLife);variance+=w*Math.pow(item.value-mean,2);});
  const effectiveCount=squaredWeight>0?totalWeight*totalWeight/squaredWeight:0;
  return {mean,sd:Math.sqrt(variance/totalWeight),count:values.length,effectiveCount};
}
function leagueScoringBaseline() {
  const rows=teamData.flatMap(team=>Object.values(team.seasons||{}).flatMap(v=>v.games||[]))
    .filter(g=>Number.isFinite(g.points_for)&&Number.isFinite(g.points_against)&&g.points_for>0&&g.points_against>0)
    .sort((a,b)=>new Date(a.date)-new Date(b.date));
  const scoring=weightedMetric(rows,"points_for",8);
  return {average:scoring?.mean??114,sd:scoring?.sd??12,count:scoring?.count??0};
}
function teamModelProfile(abbreviation, league) {
  const season=teamSeasonGames(abbreviation), rows=season.rows;
  if(rows.length<5)return null;
  const offense=weightedMetric(rows,"points_for");
  const defense=weightedMetric(rows,"points_against");
  if(!offense||!defense)return null;
  const reliability=offense.effectiveCount/(offense.effectiveCount+8);
  const defenseReliability=defense.effectiveCount/(defense.effectiveCount+8);
  const adjustedOffense=league.average+(offense.mean-league.average)*reliability;
  const adjustedDefense=league.average+(defense.mean-league.average)*defenseReliability;
  const varianceReliability=offense.effectiveCount/(offense.effectiveCount+10);
  const sd=Math.sqrt(varianceReliability*Math.pow(offense.sd,2)+(1-varianceReliability)*Math.pow(league.sd||12,2));
  return {rows,offense:adjustedOffense,defense:adjustedDefense,sd,count:rows.length,year:season.year};
}
function estimateMatchup(game) {
  const league=leagueScoringBaseline();
  const home=teamModelProfile(game.home?.abbreviation,league);
  const away=teamModelProfile(game.away?.abbreviation,league);
  if(!home||!away)return null;
  const homeMean=league.average+(home.offense-league.average)*0.55+(away.defense-league.average)*0.45+1.8;
  const awayMean=league.average+(away.offense-league.average)*0.55+(home.defense-league.average)*0.45;
  return {homeMean,awayMean,homeSd:home.sd,awaySd:away.sd,home,away,league};
}
function estimateTravelMiles(rows, teamAbbreviation, opponentAbbreviation, isHome, gameDate) {
  const prior=rows.filter(row=>new Date(row.date)<new Date(gameDate)).slice(-1)[0];
  if(!prior)return null;
  const previousVenue=prior.home_away==="home"?canonicalTeam(teamAbbreviation):canonicalTeam(prior.opponent);
  const currentVenue=isHome?canonicalTeam(teamAbbreviation):canonicalTeam(opponentAbbreviation);
  const origin=arenaData[previousVenue],destination=arenaData[currentVenue];
  if(!origin||!destination)return null;
  const radians=value=>value*Math.PI/180;
  const lat1=radians(origin.latitude),lat2=radians(destination.latitude);
  const dlat=lat2-lat1,dlon=radians(destination.longitude-origin.longitude);
  const a=Math.sin(dlat/2)**2+Math.cos(lat1)*Math.cos(lat2)*Math.sin(dlon/2)**2;
  return 3958.7613*2*Math.asin(Math.sqrt(a));
}
async function loadArenas() {
  try {
    const data=await loadJson("data/arenas.json");
    arenaData=data.teams||{};
    if(selectedGame)renderGameLineups(selectedGame);
  } catch(e) {
    arenaData={};
  }
}
function prefillGameProjections(game) {
  if(!teamUpdatedAt||!Number.isFinite(teamUpdatedAt.getTime())||Date.now()-teamUpdatedAt.getTime()>48*60*60*1000){
    $("projection-status").textContent="PASS — team history is missing or older than 48 hours. Refresh the data before using an automatic team projection.";
    return;
  }
  const projection=estimateMatchup(game);
  if(projection){
    const homeRecent=projection.home.rows.slice(-10), awayRecent=projection.away.rows.slice(-10);
    const avg=(rows,key)=>rows.length?rows.reduce((sum,row)=>sum+Number(row[key]||0),0)/rows.length:null;
    const homeBaseline=(avg(homeRecent,"points_for")+avg(awayRecent,"points_against"))/2+1.5;
    const awayBaseline=(avg(awayRecent,"points_for")+avg(homeRecent,"points_against"))/2-1.5;
    $("home-mean").value=homeBaseline.toFixed(1);
    $("away-mean").value=awayBaseline.toFixed(1);
    const homeInjuries=injuryData.filter(item=>canonicalTeam(item.team)===canonicalTeam(game.home?.abbreviation));
    const awayInjuries=injuryData.filter(item=>canonicalTeam(item.team)===canonicalTeam(game.away?.abbreviation));
    const injuryNames=items=>items.slice(0,4).map(item=>item.name+" ("+(item.status||"status unknown")+")").join(", ");
    const injuryNote=(homeInjuries.length||awayInjuries.length)?" Injury report: home "+(injuryNames(homeInjuries)||"none listed")+"; away "+(injuryNames(awayInjuries)||"none listed")+". No unsupported numeric injury penalty is applied.":"";
    const restBefore=(rows)=>{const prior=rows.filter(row=>new Date(row.date)<new Date(game.date)).slice(-1)[0];return prior?Math.max(0,Math.floor((new Date(game.date)-new Date(prior.date))/86400000)-1):null;};
    const homeRest=restBefore(projection.home.rows),awayRest=restBefore(projection.away.rows);
    const restNote=homeRest!==null&&awayRest!==null?" Scheduled rest: home "+homeRest+" days / away "+awayRest+" days.":"";
    const homeTravel=estimateTravelMiles(projection.home.rows,game.home?.abbreviation,game.away?.abbreviation,true,game.date);
    const awayTravel=estimateTravelMiles(projection.away.rows,game.away?.abbreviation,game.home?.abbreviation,false,game.date);
    const travelNote=homeTravel!==null&&awayTravel!==null?" Estimated arena-to-arena travel since prior game: home "+Math.round(homeTravel)+" mi / away "+Math.round(awayTravel)+" mi (straight-line).":"";
    $("projection-status").textContent="Default score estimates use the historical last-10 scoring/allowance baseline. Team-specific scoring variance uses "+projection.home.count+" home-team and "+projection.away.count+" away-team games across "+projection.home.year+"/"+projection.away.year+". Experimental opponent-adjusted and pace/efficiency models remain off until they beat the baseline in holdout testing. Confirmed lineups are shown separately when available; rest, travel and player on/off effects are context only and are not yet score adjustments."+restNote+travelNote+injuryNote;
    $("score-sd").value=((projection.homeSd+projection.awaySd)/2).toFixed(1);
  }else{
    $("projection-status").textContent="Insufficient team history (at least 5 games per team required). Enter manual assumptions; no model-backed projection is available.";
  }
}
function normalizeMarketText(value) {
  return String(value || "").toLowerCase().normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
}
function containsMarketPhrase(haystack, phrase) {
  const text = " " + normalizeMarketText(haystack) + " ";
  const target = " " + normalizeMarketText(phrase) + " ";
  return target.length > 2 && text.includes(target);
}
function teamMarketTokens(team) {
  const name = normalizeMarketText(team?.name || "");
  const parts = name.split(" ").filter(Boolean);
  const nickname = parts[parts.length - 1] || "";
  // Deliberately omit abbreviations: short codes create false positives
  // (for example, "PHI" inside unrelated words). Match whole team names
  // or whole nicknames only.
  return [...new Set([name, nickname].filter(value => value.length >= 4))];
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
    const eventText = [market.event_title, market.question, market.slug, market.market_group].join(" ");
    return awayTokens.some(token => containsMarketPhrase(eventText, token)) &&
      homeTokens.some(token => containsMarketPhrase(eventText, token));
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

function renderGameLineups(game) {
  const root=$("game-lineups");
  if(!root||!game)return;
  const match=lineupData.find(item=>String(item.game_id)===String(game.id));
  const age=lineupsUpdatedAt?Date.now()-lineupsUpdatedAt.getTime():Infinity;
  if(age>30*60*1000){
    root.textContent="Starting-lineup feed is stale or unavailable. No lineup adjustment is applied.";
    return;
  }
  if(!match){
    root.textContent="Starting lineups are checked near tipoff. ESPN has not supplied a lineup snapshot for this game yet.";
    return;
  }
  if(match.status!=="confirmed"){
    root.textContent="Lineups not confirmed by ESPN yet. The simulator will not guess starters or apply player-impact adjustments.";
    return;
  }
  const render=items=>items.map(player=>escapeHtml(player.name)+(player.position?" · "+escapeHtml(player.position):"")).join(", ");
  root.innerHTML='<strong>ESPN-confirmed starters</strong><p><b>'+escapeHtml(teamDisplayName(match.away_team))+'</b>: '+render(match.away_starters)+'</p><p><b>'+escapeHtml(teamDisplayName(match.home_team))+'</b>: '+render(match.home_starters)+'</p><p class="fine-print">Confirmed starter flags only. Player impact is not converted into score adjustments until it passes out-of-sample validation.</p>';
}
async function loadLineups() {
  try {
    const data=await loadJson("data/lineups.json");
    lineupData=data.games||[];
    lineupsUpdatedAt=data.last_updated?new Date(data.last_updated):null;
    if(selectedGame)renderGameLineups(selectedGame);
    if(lineupsUpdatedAt)$("data-status").textContent+=" · Lineups checked "+lineupsUpdatedAt.toLocaleTimeString();
  } catch(e) {
    lineupData=[];
    lineupsUpdatedAt=null;
    const root=$("game-lineups");
    if(root)root.textContent="Starting-lineup feed unavailable; no lineup adjustments will be applied.";
  }
}
function selectGame(game) {
  selectedGame = game;
  $("selected-title").textContent = game.name || game.short_name || "Selected matchup";
  $("game-results").textContent = "Matchup selected. Review the starting estimates and run the simulation.";
  prefillGameProjections(game);
  renderGameMarkets(game);
  renderGameLineups(game);
  if(!marketsLoaded)ensureMarketsLoaded();
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
  const projection=estimateMatchup(selectedGame);
  const homeSd=projection?Math.sqrt(0.7*Math.pow(projection.homeSd,2)+0.3*sd*sd):sd;
  const awaySd=projection?Math.sqrt(0.7*Math.pow(projection.awaySd,2)+0.3*sd*sd):sd;
  const commonShare=0.35;
  const residualShare=Math.sqrt(1-commonShare*commonShare);
  let hw=0,aw=0,homeTotal=0,awayTotal=0,ties=0,totals=[];
  for(let i=0;i<trials;i++){
    const shared=normalSample(0,1);
    const h=Math.max(50,Math.round(hm+shared*homeSd*commonShare+normalSample(0,homeSd*residualShare)));
    const a=Math.max(50,Math.round(am+shared*awaySd*commonShare+normalSample(0,awaySd*residualShare)));
    if(h>a)hw++;else if(a>h)aw++;else ties++;
    homeTotal+=h;awayTotal+=a;totals.push(h+a);
  }
  totals.sort((a,b)=>a-b);
  const avgHome=homeTotal/trials, avgAway=awayTotal/trials;
  const homeName=selectedGame.home?.name||"Home team";
  const awayName=selectedGame.away?.name||"Away team";
  const homeWinRate=hw/trials*100, awayWinRate=aw/trials*100;
  const homeWins=hw>=aw;
  const winner=homeWins?homeName:awayName;
  const projectedHome=Math.round(avgHome), projectedAway=Math.round(avgAway);
  const winnerScore=homeWins?projectedHome:projectedAway;
  const loserScore=homeWins?projectedAway:projectedHome;
  $("game-results").innerHTML=`<div class="result-grid"><div class="metric"><small>${escapeHtml(homeName)} wins</small><b>${hw.toLocaleString()}</b></div><div class="metric"><small>${escapeHtml(awayName)} wins</small><b>${aw.toLocaleString()}</b></div><div class="metric"><small>${escapeHtml(homeName)} avg. score</small><b>${avgHome.toFixed(1)}</b></div><div class="metric"><small>${escapeHtml(awayName)} avg. score</small><b>${avgAway.toFixed(1)}</b></div><div class="metric"><small>Median total</small><b>${totals[Math.floor(trials*.5)]}</b></div></div><p class="fine-print">${trials.toLocaleString()} trials. 100,000 trials using last-10 baseline score estimates, team-specific historical scoring variance and a modest shared scoring-environment shock. Experimental opponent-adjusted and pace/efficiency models are not active unless validation supports them. This is not a calibrated betting recommendation.</p>`;
  $("simulation-modal-title").textContent="Simulation result";
  $("simulation-winner").textContent="Predicted winner: "+winner;
  $("simulation-score").textContent=homeWins?homeName+" "+projectedHome+" — "+awayName+" "+projectedAway:awayName+" "+projectedAway+" — "+homeName+" "+projectedHome;
  const homeLogo=teamLogoMarkup(selectedGame.home,"split-home");
  const awayLogo=teamLogoMarkup(selectedGame.away,"split-away");
  $("simulation-confidence").innerHTML=`<div class="split-result-team split-result-home" style="${teamColorStyle(selectedGame.home)}"><div class="split-result-identity">${homeLogo}</div><div class="split-result-team-name">${escapeHtml(homeName)}</div><div class="split-result-wins">${hw.toLocaleString()} WINS</div><div class="split-result-probability">${homeWinRate.toFixed(1)}%</div></div><div class="split-result-versus">VS</div><div class="split-result-team split-result-away" style="${teamColorStyle(selectedGame.away)}"><div class="split-result-identity">${awayLogo}</div><div class="split-result-team-name">${escapeHtml(awayName)}</div><div class="split-result-wins">${aw.toLocaleString()} WINS</div><div class="split-result-probability">${awayWinRate.toFixed(1)}%</div></div>${ties?`<p class="split-result-ties">Tied games: ${ties.toLocaleString()}</p>`:""}`;
  $("simulation-modal").hidden=false;
  $("simulation-modal-close").focus();
}

function erf(x){const sign=x<0?-1:1;x=Math.abs(x);const t=1/(1+0.3275911*x);const y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);return sign*y;}
function calcProp(){
  const mean=Number($("prop-mean").value),sd=Number($("prop-sd").value),line=Number($("prop-line").value);
  if(selectedPlayer){
    if(!playerUpdatedAt || !Number.isFinite(playerUpdatedAt.getTime()) || Date.now()-playerUpdatedAt.getTime()>48*60*60*1000){
      $("prop-results").textContent="PASS — player game logs are missing or older than 48 hours. Refresh the player database before using a player projection.";
      return;
    }
    if(!injuryUpdatedAt || !Number.isFinite(injuryUpdatedAt.getTime()) || Date.now()-injuryUpdatedAt.getTime()>24*60*60*1000){
      $("prop-results").textContent="PASS — the injury feed is missing or older than 24 hours. Refresh current availability before using a player projection.";
      return;
    }
    const injury=injuryData.find(item=>String(item.athlete_id)===String(selectedPlayer.id));
    const status=String(injury?.status||"").toLowerCase();
    if(injury && ["out","doubtful","questionable","day-to-day","game time decision"].some(flag=>status.includes(flag))){
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
    const recentFive=minuteSample.slice(0,Math.min(5,minuteSample.length));
    const recentFiveAvg=recentFive.reduce((sum,value)=>sum+value,0)/recentFive.length;
    const minuteVariance=minuteSample.reduce((sum,value)=>sum+Math.pow(value-avgMinutes,2),0)/Math.max(1,minuteSample.length-1);
    if(avgMinutes<15||Math.sqrt(minuteVariance)>8||recentFiveAvg<12){
      $("prop-results").textContent="PASS — "+selectedPlayer.name+" has an unstable or limited recent minutes role (average "+avgMinutes.toFixed(1)+" minutes; last-five average "+recentFiveAvg.toFixed(1)+"; variability "+Math.sqrt(minuteVariance).toFixed(1)+").";
      return;
    }
  }
  if(![mean,sd,line].every(Number.isFinite)||sd<=0){$("prop-results").textContent="Enter valid values and a positive standard deviation.";return;}
  const normalOver=(1-erf((line-mean)/(sd*Math.sqrt(2))))/2;
  let over=normalOver;
  let empiricalNote="";
  if(selectedPlayer){
    const nonPush=selectedPlayerLogs.map(game=>game[$("prop-stat").value]).filter(value=>Number.isFinite(value)&&value!==line);
    const hits=nonPush.filter(value=>value>line).length;
    if(nonPush.length){
      const empiricalOver=(hits+1)/(nonPush.length+2);
      const empiricalWeight=nonPush.length/(nonPush.length+12);
      over=normalOver*(1-empiricalWeight)+empiricalOver*empiricalWeight;
      empiricalNote='<p class="fine-print">Recent sample: '+hits+'/'+nonPush.length+' non-push games went Over ('+(empiricalOver*100).toFixed(1)+'% smoothed empirical rate). Blended with the minutes-adjusted normal estimate at '+Math.round(empiricalWeight*100)+'% empirical weight. This is not fully calibrated.</p>';
    }
  }
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
  $("prop-results").innerHTML=`<div class="result-grid"><div class="metric"><small>Over probability</small><b>${fmt(over*100)}</b></div><div class="metric"><small>Under probability</small><b>${fmt((1-over)*100)}</b></div></div><p class="fine-print">Player estimate blends a minutes-adjusted normal projection with the recent empirical hit rate. It is not fully calibrated and is not a confirmed lineup or official minutes projection.</p>`+empiricalNote+marketComparison;
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
  const root=$("markets");
  if(root) root.innerHTML='<p class="muted">Refreshing Polymarket snapshot…</p>';
  try {
    const data=await loadJson('data/polymarket.json');
    const rows=Array.isArray(data.markets)?data.markets:[]; marketData=rows; marketsLoaded=true;
    if(!root) return;
    root.innerHTML=rows.length?rows.slice(0,150).map(m=>'<div class="market"><div><strong>'+escapeHtml(m.question||'Untitled market')+'</strong><small>'+escapeHtml(m.event_title||'')+(m.market_type?' · '+escapeHtml(m.market_type.replace('_',' ')):'')+(marketPriceSummary(m)?' · '+marketPriceSummary(m):' · Prices unavailable')+' · 24h volume: '+escapeHtml(m.volume_24h??'n/a')+' · Liquidity: '+escapeHtml(m.liquidity??'n/a')+'</small></div>'+(m.url?'<a target="_blank" rel="noopener" href="'+escapeHtml(m.url)+'">Open market</a>':'')+'</div>').join(''):'<p class="muted">No active NBA markets were found in the latest public snapshot.</p>' + '<p class="fine-print">Snapshot updated '+(data.last_updated?new Date(data.last_updated).toLocaleString():'at an unknown time')+'.</p>';
    if(rows.length) root.insertAdjacentHTML('beforeend','<p class="fine-print">Showing '+Math.min(rows.length,150)+' of '+rows.length+' markets · Snapshot updated '+(data.last_updated?new Date(data.last_updated).toLocaleString():'at an unknown time')+'.</p>');
    if(selectedGame) renderGameMarkets(selectedGame); if(selectedPlayer) renderPlayerMarkets(selectedPlayer);
  } catch(e) { marketsLoaded=false; marketData=[]; if(root) root.innerHTML='<p class="muted">Polymarket data could not be loaded: '+escapeHtml(e.message)+'. Try Refresh Markets.</p>'; }
}
async function ensureMarketsLoaded() {
  if(marketsLoaded)return;
  if(marketsLoading){await marketsLoading;return;}
  marketsLoading=loadMarkets();
  try{await marketsLoading;}finally{marketsLoading=null;}
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
function renderPlayerSearch() {
  const root = $("player-search-results");
  const query = ($("player-search").value || "").trim().toLowerCase();
  if (!query) { root.innerHTML = ""; return; }
  if (!players.length && !teamData.length) { root.innerHTML = '<p class="muted">Player and team databases are still loading.</p>'; return; }
  const playerMatches = players.filter(p => [p.name,p.team,p.position].some(v => String(v || "").toLowerCase().includes(query))).slice(0,15);
  const teamMatches = teamData.filter(t => [teamDisplayName(t.abbreviation),t.abbreviation].some(v => String(v || "").toLowerCase().includes(query))).slice(0,10);
  if (!playerMatches.length && !teamMatches.length) { root.innerHTML = '<p class="muted">No players or teams match that search.</p>'; return; }
  const playerHtml = playerMatches.length ? '<h3 class="search-group-title">Players</h3>' + playerMatches.map(p => {
    const injury = injuryData.find(item => String(item.athlete_id) === String(p.id));
    const availability = injury ? ' · Injury: ' + (injury.status || 'listed') : '';
    const gameCount = Object.values(p.seasons || {}).reduce((sum, logs) => sum + (Array.isArray(logs) ? logs.length : 0), 0);
    return '<div class="game"><div><strong>' + escapeHtml(p.name) + '</strong><small>' + escapeHtml(p.team) + ' · ' + escapeHtml(p.position || 'Position n/a') + ' · ' + escapeHtml(p.status) + ' · ' + gameCount + ' game logs' + escapeHtml(availability) + '</small></div><button data-player-id="' + escapeHtml(p.id) + '">Run Simulation</button></div>';
  }).join('') : '';
  const teamHtml = teamMatches.length ? '<h3 class="search-group-title">Teams</h3>' + teamMatches.map(t => '<div class="game"><div><strong>' + escapeHtml(teamDisplayName(t.abbreviation)) + '</strong><small>' + escapeHtml(t.abbreviation) + ' · Historical team records and game statistics</small></div><button data-team-abbr="' + escapeHtml(t.abbreviation) + '">View Team Stats</button></div>').join('') : '';
  root.innerHTML = playerHtml + teamHtml;
  root.querySelectorAll('[data-player-id]').forEach(b => b.addEventListener('click', () => {
    showPlayer(b.dataset.playerId); calcProp(); $("prop-results").scrollIntoView({behavior:'smooth',block:'nearest'});
  }));
  root.querySelectorAll('[data-team-abbr]').forEach(b => b.addEventListener('click', () => {
    showTeam(b.dataset.teamAbbr); $("team-detail").scrollIntoView({behavior:'smooth',block:'nearest'});
  }));
}
function renderSelectedPlayerForProp() {
  const root = $("prop-selected-player");
  if (!root) return;
  if (!selectedPlayer) {
    root.textContent = "No player selected. Search above and select a player to load their recent game history.";
    return;
  }
  root.innerHTML = "<strong>" + escapeHtml(selectedPlayer.name) + "</strong> · " + escapeHtml(selectedPlayer.team || "Team unavailable") +
    " · " + selectedPlayerLogs.length + " recent game logs loaded. Choose a stat and line below to calculate this player’s projection.";
}

function applyPlayerHistoricalBaseline() {
  renderSelectedPlayerForProp();
  if (!selectedPlayer || !selectedPlayerLogs.length) {
    $("prop-source-status").textContent = selectedPlayer
      ? "No game-log sample is available for " + selectedPlayer.name + "."
      : "Select a player below to load a historical baseline, or enter assumptions manually.";
    return;
  }
  const stat = $("prop-stat").value;
  const rows = selectedPlayerLogs.filter(g => Number.isFinite(g[stat]));
  const minuteRows = rows.filter(g => Number.isFinite(g.minutes) && g.minutes > 0);
  if (rows.length < 5 || minuteRows.length < 5) {
    $("prop-source-status").textContent = "Insufficient recent " + stat + " and minutes data to build a role-adjusted baseline.";
    return;
  }
  const weighted = (values, halfLife=4) => {
    let total=0, sum=0;
    values.forEach((value,index)=>{const weight=Math.pow(0.5,index/halfLife);total+=weight;sum+=value*weight;});
    return total ? sum/total : null;
  };
  // Logs are newest-first. A recent-minutes blend reacts to role changes,
  // while per-minute production is smoothed over the same recent sample.
  const minutes = minuteRows.map(g=>g.minutes);
  const allMinutes = weighted(minutes);
  const recentMinutes = weighted(minutes.slice(0,Math.min(5,minutes.length)),3);
  const projectedMinutes = 0.65*recentMinutes+0.35*allMinutes;
  const perMinute = rows.filter(g=>Number.isFinite(g.minutes)&&g.minutes>0)
    .map(g=>g[stat]/g.minutes);
  const rate = weighted(perMinute);
  const rateMean = perMinute.reduce((a,b)=>a+b,0)/perMinute.length;
  const rateVariance = perMinute.length>1
    ? perMinute.reduce((sum,v)=>sum+Math.pow(v-rateMean,2),0)/(perMinute.length-1) : 0;
  const minuteMean = minutes.reduce((a,b)=>a+b,0)/minutes.length;
  const minuteVariance = minutes.length>1
    ? minutes.reduce((sum,v)=>sum+Math.pow(v-minuteMean,2),0)/(minutes.length-1) : 0;
  const adjustedMean = rate*projectedMinutes;
  const adjustedSd = Math.sqrt(Math.pow(Math.sqrt(rateVariance)*projectedMinutes,2)+Math.pow(rate*Math.sqrt(minuteVariance),2));
  $("prop-mean").value = adjustedMean.toFixed(1);
  $("prop-sd").value = Math.max(1,adjustedSd).toFixed(1);
  const injury = injuryData.find(item => String(item.athlete_id) === String(selectedPlayer.id));
  const injuryWarning = injury
    ? " ESPN injury report: " + (injury.status || "status unspecified") + (injury.type ? " (" + injury.type + ")" : "") + "."
    : "";
  const freshness = injuryUpdatedAt ? " Injury feed age: " + Math.max(0,Math.round((Date.now()-injuryUpdatedAt.getTime())/60000)) + " minutes." : " Injury feed timestamp unavailable.";
  $("prop-source-status").textContent = selectedPlayer.name + " · " + stat.toUpperCase() +
    " minutes-adjusted historical estimate from " + rows.length + " recent games. Estimated minutes: " +
    projectedMinutes.toFixed(1) + " (last-5 trend blended with last-10 baseline)." +
    " This is still not a confirmed lineup/minutes projection." + injuryWarning + freshness;
}
function renderPlayerMarkets(player) {
  const root = $("player-market-matches");
  if (!root || !player) return;
  const playerName = normalizeMarketText(player.name);
  const matches = marketData.filter(market =>
    containsMarketPhrase([market.question, market.market_group, market.slug].join(" "), playerName)
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


function normalizeImpactName(value) {
  return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
}
function impactSeasonFromEspn(season) {
  return String(season) === "2027" ? "2026-27" : String(season) === "2026" ? "2025-26" : null;
}
function findPlayerImpact(player, espnSeason) {
  const season = impactSeasonFromEspn(espnSeason);
  if (!season || !playerImpactData.length) return null;
  const name = normalizeImpactName(player.name);
  const team = canonicalTeam(player.team);
  let matches = playerImpactData.filter(row => row.season === season && normalizeImpactName(row.name) === name && canonicalTeam(row.team) === team);
  if (!matches.length) matches = playerImpactData.filter(row => row.season === season && normalizeImpactName(row.name) === name);
  if (!matches.length && season === "2026-27") {
    matches = playerImpactData.filter(row => row.season === "2025-26" && normalizeImpactName(row.name) === name && canonicalTeam(row.team) === team);
    if (!matches.length) matches = playerImpactData.filter(row => row.season === "2025-26" && normalizeImpactName(row.name) === name);
  }
  return matches.length === 1 ? matches[0] : matches.find(row => canonicalTeam(row.team) === team) || null;
}
async function loadPlayerImpact() {
  if (playerImpactLoaded) return;
  if (playerImpactLoading) return playerImpactLoading;
  playerImpactLoading = (async () => {
    try {
      const data = await loadJson("data/player_impact.json");
      playerImpactData = data.players || [];
      playerImpactLoaded = true;
      if (data.last_updated) $("data-status").textContent += " · HAPM updated " + new Date(data.last_updated).toLocaleDateString();
    } catch (e) {
      playerImpactData = [];
      console.warn("Player impact data unavailable:", e.message);
    }
  })();
  try { await playerImpactLoading; } finally { playerImpactLoading = null; }
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
  const impact = findPlayerImpact(p, season);
  const impactHtml = impact
    ? '<div class="metric"><small>HAPM impact · pts/100</small><b>' + (impact.net > 0 ? '+' : '') + Number(impact.net).toFixed(1) + '</b></div><div class="metric"><small>HAPM offense</small><b>' + (impact.offense > 0 ? '+' : '') + Number(impact.offense).toFixed(1) + '</b></div><div class="metric"><small>HAPM defense</small><b>' + (impact.defense > 0 ? '+' : '') + Number(impact.defense).toFixed(1) + '</b></div><div class="metric"><small>HAPM possessions</small><b>' + Number(impact.possessions).toLocaleString() + '</b></div>'
    : '<div class="metric"><small>HAPM impact</small><b>Not rated</b></div>';
  const sortedLogs = [...logs].sort((a,b) => new Date(b.date || 0) - new Date(a.date || 0));
  const recent = sortedLogs.slice(0,10);
  selectedPlayer = p;
  selectedPlayerLogs = recent;
  applyPlayerHistoricalBaseline();
  const avg = key => {
    const vals = recent.map(g=>g[key]).filter(v=>Number.isFinite(v));
    return vals.length ? (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1) : "n/a";
  };
  const impactRows=recent.filter(g=>Number.isFinite(g.plus_minus)&&Number.isFinite(g.minutes)&&g.minutes>0);
  const plusMinus36=impactRows.length
    ? (impactRows.reduce((sum,g)=>sum+g.plus_minus,0)/impactRows.reduce((sum,g)=>sum+g.minutes,0)*36).toFixed(1)
    : "n/a";
  const rows = sortedLogs.slice(0,15).map(g => '<tr><td>' + escapeHtml(g.date ? new Date(g.date).toLocaleDateString() : "—") + '</td><td>' + escapeHtml(g.opponent || "—") + '</td><td>' + escapeHtml(g.result || "—") + '</td><td>' + (g.minutes ?? "—") + '</td><td>' + (g.points ?? "—") + '</td><td>' + (g.rebounds ?? "—") + '</td><td>' + (g.assists ?? "—") + '</td></tr>').join("");
  $("player-detail").innerHTML = '<h3>' + escapeHtml(p.name) + ' · ' + escapeHtml(p.team) + ' · Season ' + escapeHtml(season) + '</h3><div class="result-grid"><div class="metric"><small>Last 10 PTS avg</small><b>' + avg("points") + '</b></div><div class="metric"><small>Last 10 REB avg</small><b>' + avg("rebounds") + '</b></div><div class="metric"><small>Last 10 AST avg</small><b>' + avg("assists") + '</b></div><div class="metric"><small>Last 10 MIN avg</small><b>' + avg("minutes") + '</b></div><div class="metric"><small>Unadjusted +/- per 36</small><b>' + plusMinus36 + '</b></div>' + impactHtml + '</div><div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th></tr></thead><tbody>' + rows + '</tbody></table></div><p class="fine-print">Last 10 averages use available numeric game logs only. Historical logs are descriptive, not projections. Plus/minus per 36 is an unadjusted on-court signal. HAPM is a separate held-out adjusted plus-minus rating (3/3 blend, points per 100 possessions, 250+ possession minimum) from <a href="https://lumahoops.org/luma" target="_blank" rel="noopener">LUMA Basketball Research</a> (CC BY 4.0). HAPM is shown as context only and is not yet used to adjust game scores pending simulator backtesting.</p><div id="player-market-matches"></div>';
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
    injuryUpdatedAt = data.last_updated ? new Date(data.last_updated) : null;
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
    teamUpdatedAt = data.last_updated ? new Date(data.last_updated) : null;
    renderPlayerSearch();
    if (data.last_updated) $("data-status").textContent += " · Teams " + teamData.length + " updated " + new Date(data.last_updated).toLocaleString();
  } catch (e) {
    teamData = [];
  }
}
async function loadModelMetrics() {
  const root=$("model-validation");
  if(!root)return;
  try {
    const data=await loadJson("data/model_metrics.json");
    if(!data.games_tested){root.textContent=data.message||"Not enough historical games to evaluate the model yet.";return;}
    let qualityHtml="";
    try {
      const quality=await loadJson("data/data_quality.json");
      const warnings=(quality.warnings||[]).slice(0,3);
      qualityHtml='<p class="fine-print">Archive integrity audit: '+escapeHtml(String(quality.status||"unknown").toUpperCase())+
        ' · '+Number(quality.team_history?.team_count||0)+'/30 teams · '+warnings.length+' displayed warning(s).'+
        (warnings.length?' '+warnings.map(escapeHtml).join(" "):"")+'</p>';
    } catch(e) {
      qualityHtml='<p class="fine-print">Archive integrity audit will appear after the next successful multi-season refresh.</p>';
    }
    const modelEnough=data.games_tested>=500;
    const modelBetter=modelEnough&&data.model_score_mae<data.baseline_score_mae&&data.model_winner_accuracy>data.baseline_winner_accuracy&&data.model_brier_score<data.baseline_brier_score&&data.model_calibration_error<data.baseline_calibration_error;
    const advancedEnough=data.advanced_games_tested>=500;
    const advancedBetter=advancedEnough&&data.advanced_score_mae<data.advanced_baseline_score_mae&&data.advanced_winner_accuracy>data.advanced_baseline_winner_accuracy&&data.advanced_brier_score<data.advanced_baseline_brier_score&&data.advanced_calibration_error<data.advanced_baseline_calibration_error;
    root.innerHTML='<strong>Walk-forward validation · '+Number(data.games_tested).toLocaleString()+' games</strong>'+
      '<div class="result-grid">'+
      '<div class="metric"><small>Experimental score MAE</small><b>'+Number(data.model_score_mae).toFixed(2)+' pts</b></div>'+
      '<div class="metric"><small>Last-10 baseline MAE</small><b>'+Number(data.baseline_score_mae).toFixed(2)+' pts</b></div>'+
      '<div class="metric"><small>Experimental winner accuracy</small><b>'+(Number(data.model_winner_accuracy)*100).toFixed(1)+'%</b></div>'+
      '<div class="metric"><small>Baseline winner accuracy</small><b>'+(Number(data.baseline_winner_accuracy)*100).toFixed(1)+'%</b></div>'+
      '<div class="metric"><small>Experimental Brier score</small><b>'+Number(data.model_brier_score).toFixed(3)+'</b></div>'+
      '<div class="metric"><small>Baseline Brier score</small><b>'+(data.baseline_brier_score==null?'n/a':Number(data.baseline_brier_score).toFixed(3))+'</b></div></div>'+
      '<p class="fine-print">Probability calibration error — experimental: '+(data.model_calibration_error==null?'n/a':Number(data.model_calibration_error).toFixed(3))+' · baseline: '+(data.baseline_calibration_error==null?'n/a':Number(data.baseline_calibration_error).toFixed(3))+'. Lower Brier and calibration error are better.</p>'+
      '<p class="fine-print">'+(!modelEnough?"At least 500 chronological holdout games are required before considering promotion.":modelBetter?"Experimental model leads on all four validation measures.":"The experimental blend has not beaten the baseline on all four measures; default score estimates remain on the baseline.")+'</p>'+
      (data.advanced_games_tested?'<strong>Experimental pace / efficiency / rest / travel model · '+Number(data.advanced_games_tested).toLocaleString()+' matched holdout games</strong><div class="result-grid"><div class="metric"><small>Efficiency model MAE</small><b>'+Number(data.advanced_score_mae).toFixed(2)+' pts</b></div><div class="metric"><small>Same-game baseline MAE</small><b>'+Number(data.advanced_baseline_score_mae).toFixed(2)+' pts</b></div><div class="metric"><small>Efficiency winner accuracy</small><b>'+(Number(data.advanced_winner_accuracy)*100).toFixed(1)+'%</b></div><div class="metric"><small>Same-game baseline accuracy</small><b>'+(Number(data.advanced_baseline_winner_accuracy)*100).toFixed(1)+'%</b></div><div class="metric"><small>Efficiency Brier score</small><b>'+Number(data.advanced_brier_score).toFixed(3)+'</b></div></div><p class="fine-print">Calibration error: '+(data.advanced_calibration_error==null?'n/a':Number(data.advanced_calibration_error).toFixed(3))+'. '+(!advancedEnough?"At least 500 matched holdout games are required before considering promotion.":advancedBetter?"The experimental schedule-aware model leads on all four validation measures.":"The experimental schedule-aware model has not beaten the baseline on all four measures; it remains disabled in the default score projection.")+'</p>':'<p class="fine-print">Pace/efficiency model awaits enough completed boxscores with all required statistics.</p>')+
      '<p class="fine-print">Last updated: '+(data.generated_at?new Date(data.generated_at).toLocaleString():"unknown")+'. Multi-season walk-forward results are preliminary, not proof of future accuracy.</p>'+qualityHtml;
  } catch(e) {
    root.textContent="Walk-forward validation metrics will appear after the next successful team-data refresh.";
  }
}
async function loadPlayers() {
  try {
    const data = await loadJson("data/players.json");
    players = data.players || [];
    await loadPlayerImpact();
    playerUpdatedAt = data.last_updated ? new Date(data.last_updated) : null;
    playersLoaded = true;
    renderPlayerSearch();
    if (data.last_updated) $("data-status").textContent += " · Players " + players.length + " updated " + new Date(data.last_updated).toLocaleString();
  } catch (e) {
    playersLoaded = false;
    $("player-search-results").textContent = "Player database unavailable: " + e.message;
  }
}
async function ensurePlayersLoaded() {
  if(playersLoaded)return;
  if(playersLoading){await playersLoading;return;}
  playersLoading=loadPlayers();
  try{await playersLoading;}finally{playersLoading=null;}
}

async function loadAll(){
  try{const data=await loadJson("data/games.json");games=data.games||[];$("data-status").textContent="ESPN updated "+(data.last_updated?new Date(data.last_updated).toLocaleString():"time unavailable");showGames();}catch(e){$("data-status").textContent="Game feed unavailable";$("games").textContent=e.message;}
  if(playersLoaded) await loadPlayers();
  await loadTeams();
  await loadArenas();
  await loadModelMetrics();
  await loadInjuries();
  await loadLineups();
  if(marketsLoaded) await loadMarkets();
}
$("simulate").addEventListener("click",runGameSimulation);
$("day-prev").addEventListener("click",()=>{activeScheduleDay=Math.max(0,activeScheduleDay-1);updateDayNavigation();});
$("day-next").addEventListener("click",()=>{activeScheduleDay=Math.min(scheduleDays.length-1,activeScheduleDay+1);updateDayNavigation();});
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{
  document.querySelectorAll("[data-view]").forEach(tab=>{const active=tab===button;tab.classList.toggle("active",active);tab.setAttribute("aria-selected",String(active));});
  document.querySelectorAll(".view-panel").forEach(panel=>panel.hidden=panel.id!==button.dataset.view);
  if(button.dataset.view==="players-view") ensurePlayersLoaded();
  if(button.dataset.view==="markets-view") ensureMarketsLoaded();
}));
$("prop-calc").addEventListener("click",calcProp);
$("prop-stat").addEventListener("change",()=>{selectedPropMarket=null;applyPlayerHistoricalBaseline();});
$("prop-line").addEventListener("input",()=>{selectedPropMarket=null;});
$("reload").addEventListener("click",loadAll);
$("refresh-markets").addEventListener("click",loadMarkets);
$("player-search").addEventListener("input",renderPlayerSearch);
loadAll();

$("simulation-modal-close").addEventListener("click",()=>{$("simulation-modal").hidden=true;});
$("simulation-modal-done").addEventListener("click",()=>{$("simulation-modal").hidden=true;});
$("simulation-modal").addEventListener("click",event=>{if(event.target.id==="simulation-modal") $("simulation-modal").hidden=true;});
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!$("simulation-modal").hidden) $("simulation-modal").hidden=true;});
