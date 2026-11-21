const $ = (id) => document.getElementById(id);
let games = [];
let selectedGame = null;
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
function selectGame(game) {
  selectedGame = game;
  $("selected-title").textContent = game.name || game.short_name || "Selected matchup";
  $("game-results").textContent = "Matchup selected. Set assumptions and run the simulation.";
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
  $("game-results").innerHTML=`<div class="result-grid"><div class="metric"><small>Home win</small><b>${fmt(hw/trials*100)}</b></div><div class="metric"><small>Away win</small><b>${fmt(aw/trials*100)}</b></div><div class="metric"><small>Avg. home score</small><b>${(homeTotal/trials).toFixed(1)}</b></div><div class="metric"><small>Avg. away score</small><b>${(awayTotal/trials).toFixed(1)}</b></div><div class="metric"><small>Median total</small><b>${totals[Math.floor(trials*.5)]}</b></div></div><p class="fine-print">${trials.toLocaleString()} trials. Independent normal score assumptions; no team/player data adjustment yet. Treat as a calculator, not a betting recommendation.</p>`;
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
async function loadAll(){
  try{const data=await loadJson("data/games.json");games=data.games||[];$("data-status").textContent="ESPN updated "+(data.last_updated?new Date(data.last_updated).toLocaleString():"time unavailable");showGames();}catch(e){$("data-status").textContent="Game feed unavailable";$("games").textContent=e.message;}
  await loadMarkets();
}
$("simulate").addEventListener("click",runGameSimulation);
$("prop-calc").addEventListener("click",calcProp);
$("reload").addEventListener("click",loadAll);
loadAll();
