// Bütün sayfaların ortak üst menüsü: gruplu, kaydırmasız; son açılan sekmeyi hatırlar.
// Kullanım: <nav id="topnav"></nav><script src="nav.js"></script>
(function(){
  var GROUPS=[
    ["Craft",[["craft","Craft","./#craft",1],["alchemy","Alchemy","./#alchemy"],["food","Cooking","./#food"],["enchant","Enchant Yükseltme","./#enchant"]]],
    ["Toplama",[["farm","Farming","./#farm"],["refine","Refining","./#refine"]]],
    ["Pazar",[["bm","Black Market Flips","./#bm"],["db","Item Database","./#db"]]],
    ["Oyuncu",[["builds","Builds","builds.html"],["destiny","Destiny Board","destiny.html"],["dps","DPS Meter","dps.html"],["party","Parti Set","party.html"]]]
  ];
  var URL_OF={};GROUPS.forEach(function(g){g[1].forEach(function(t){URL_OF[t[0]]=t[2]})});
  var HASH={"#food":"food","#craft":"craft","#bm":"bm","#db":"db","#farm":"farm","#refine":"refine","#enchant":"enchant","#alchemy":"alchemy"};
  var path=location.pathname.replace(/\.html$/,"");
  var page=/\/builds$/.test(path)?"builds":/\/destiny$/.test(path)?"destiny":/\/dps$/.test(path)?"dps":/\/party$/.test(path)?"party":(HASH[location.hash]||"alchemy");
  var isIndex=!/\/(builds|destiny|dps|party)$/.test(path);
  var store=function(k,v){try{v===undefined?localStorage.removeItem(k):localStorage.setItem(k,v)}catch(e){}};
  var load=function(k){try{return localStorage.getItem(k)}catch(e){return null}};

  // Siteye ilk girişte (bu oturumda), ana sayfa düz açıldıysa son kalınan sekmeye geç
  var first=true;try{first=!sessionStorage.getItem("aonav");sessionStorage.setItem("aonav","1")}catch(e){first=false}
  var last=load("aolasttab");
  // Panelden kapatılan sekmeler (auth.js güncel listeyi getirip buraya yazar; ilk çizimde önbellekteki kullanılır)
  var OFF={off:[],admin:false};try{OFF=JSON.parse(load("aoTabsOff")||"null")||OFF}catch(e){}
  var isOff=function(k){return OFF.off.indexOf(k)>=0};
  if(first&&isIndex&&!location.hash&&last&&last!=="alchemy"&&URL_OF[last]&&!isOff(last)){location.replace(URL_OF[last]);return}
  store("aolasttab",page);

  var css=".nv{display:flex;flex-wrap:wrap;gap:8px;margin:0}"
    +".nvg{display:flex;align-items:center;flex-wrap:wrap;gap:2px;padding:4px;background:var(--card,#11161d);border:1px solid var(--line,#252d38);border-radius:12px;min-width:0}"
    +".nvg>span{font:700 10px/1 Inter,system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--acc,#f0883e);padding:0 8px 0 6px}"
    +".nvg a{display:inline-flex;align-items:center;font:600 14px/1.2 Inter,system-ui,sans-serif;color:var(--mut,#8b95a3);text-decoration:none;padding:8px 12px;border:1px solid transparent;border-radius:9px;white-space:nowrap}"
    +".nvg a:hover{color:var(--ink,#e6e9ee);background:var(--card2,#151b23)}"
    +".nvg a.on{background:var(--acc2,#7a3e16);color:var(--accT,#ffd6b3);border-color:#b8602a}"
    +".nvg a:focus-visible{outline:2px solid var(--acc,#f0883e);outline-offset:2px}"
    +"@media(max-width:700px){.nvg{flex:1 1 100%}.nvg a{padding:7px 10px;font-size:13px}}";
  var st=document.createElement("style");st.textContent=css;document.head.appendChild(st);

  var el=document.getElementById("topnav");if(!el)return;
  el.className="nv";el.setAttribute("aria-label","Sayfalar");
  el.innerHTML=GROUPS.map(function(g){
    return '<div class="nvg"><span>'+g[0]+'</span>'+g[1].map(function(t){
      var on=t[0]===page;
      return '<a href="'+t[2]+'" data-k="'+t[0]+'" class="'+(on?"on":"")+(t[3]?" pin":"")+'"'+(on?' aria-current="page"':"")+'>'+t[1]+'</a>';
    }).join("")+'</div>';
  }).join("");
  function apply(off,admin){
    OFF={off:off||[],admin:!!admin};
    el.querySelectorAll("a[data-k]").forEach(function(a){
      var o=isOff(a.dataset.k);
      a.hidden=o&&!OFF.admin;
      var m=a.querySelector(".nvx");if(m)m.remove();
      if(o&&OFF.admin)a.insertAdjacentHTML("beforeend",'<small class="nvx" style="margin-left:6px;font-size:10px;color:var(--warn,#e3b341)">kapalı</small>');
    });
    el.querySelectorAll(".nvg").forEach(function(g){g.hidden=!g.querySelector("a[data-k]:not([hidden])")});
  }
  apply(OFF.off,OFF.admin);
  window.aoNav={page:page,apply:apply,home:function(){for(var k in URL_OF)if(!isOff(k))return URL_OF[k];return "./"},set:function(off,admin){store("aoTabsOff",JSON.stringify({off:off||[],admin:!!admin}));apply(off,admin)}};
  // Ana sayfa içindeki sekmeler sadece #'i değiştirir; sayfa sekmeyi açılışta okuduğu için yeniden yüklenir
  el.addEventListener("click",function(e){
    var a=e.target.closest&&e.target.closest("a[data-k]");if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.button)return;
    var u=new URL(a.getAttribute("href"),location.href);
    if(isIndex&&u.pathname.replace(/index(\.html)?$/,"")===location.pathname.replace(/index(\.html)?$/,"")){e.preventDefault();location.hash=u.hash;location.reload()}
  });
})();
