// Destiny Board seviyeleri: Craft, Cooking, Alchemy, Farming ve Refining spec alanlarını otomatik doldurur.
// Kaynak sırası destiny.html ile aynı: toplayıcı (canlı) > hesaptaki kayıt (destiny_boards) > bu tarayıcıda elle girilen.
// window.aoSpec.lv(düğüm) seçili karakterin seviyesini (0-100) verir; board yoksa null.
(()=>{
  const API="http://127.0.0.1:47700",K="aospecchr",MANUAL="Bu tarayıcı (elle)";
  let N=null,idx={},LIVE=null,BOARDS={},MAN={},chr="",msg="";
  const subs=[];
  const get=(k,d)=>{try{return JSON.parse(localStorage.getItem(k))||d}catch(e){return d}};
  const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const names=()=>[...new Set([...(LIVE&&LIVE.char?[LIVE.char]:[]),...Object.keys(BOARDS),...(Object.keys(MAN).length?[MANUAL]:[])])];
  const board=()=>chr&&chr!==MANUAL&&(LIVE&&LIVE.char===chr?LIVE:BOARDS[chr])||null;
  function lv(id){
    if(!N||!N[id]||!chr)return null;
    if(chr===MANUAL)return Math.min(100,+MAN[id]||0);
    const b=board();if(!b)return null;
    const i=idx[id];
    // max: oyunun "sonuna ulaştı" dediği düğümler (seviyeleri ayrıca gelmez)
    if(b.max&&b.max.includes(i))return 100;
    return Math.min(100,+(b.lv&&b.lv[i])||0);
  }
  // Seçim değişince ya da veri gelince değişen anahtar: sayfa aynı anahtarla bir kez doldurur, sonra elle düzenleme korunur
  const key=()=>{if(!N||!chr)return "";if(chr===MANUAL)return chr+"|"+JSON.stringify(MAN).length;const b=board();return b?chr+"|"+(b.ts||0):""};
  // Eşya kimliği (tier'sız) -> düğüm; ilk verilen şablon önceliklidir (aynı ikonlu ana düğüm yerine spec düğümü)
  function iconMap(tpls){const m={};tpls.forEach(t=>Object.entries(N||{}).forEach(([id,n])=>{if(n.tpl===t&&n.icon){const b=n.icon.replace(/^T\d_/,"").replace(/@\d$/,"");if(!(b in m))m[b]=id}}));return m}
  function draw(){
    const L=names();
    document.querySelectorAll(".dsbar").forEach(el=>{
      if(!N){el.innerHTML="";return}
      if(!L.length){el.innerHTML=`Destiny Board bulunamadı. <a href="destiny.html">Destiny Board</a> sayfasında board'unu kaydedersen (ya da DPS Meter toplayıcısı açıkken) spec'ler buraya otomatik gelir.${msg?" ("+esc(msg)+")":""}`;return}
      const b=board(),src=chr===MANUAL?"elle girilen seviyeler":b===LIVE?"toplayıcıdan canlı":"hesabındaki kayıt";
      el.innerHTML=`Destiny Board: <select class="dssel" aria-label="Karakter">${L.map(c=>`<option${c===chr?" selected":""}>${esc(c)}</option>`).join("")}</select> <span>${esc(src)} · spec'ler otomatik dolduruldu, elle değiştirebilirsin (sayfa yenilenince board'dan tekrar gelir).</span>`;
      el.querySelector("select").onchange=e=>{chr=e.target.value;try{localStorage.setItem(K,JSON.stringify(chr))}catch(x){}draw();subs.forEach(f=>f())};
    });
  }
  const done=()=>{const L=names();if(!L.includes(chr))chr=L.includes(get("aodestiny1",{}).chr)?get("aodestiny1",{}).chr:L[0]||"";draw();subs.forEach(f=>f())};
  window.aoSpec={lv,key,iconMap,nodes:()=>N,draw,on:f=>{subs.push(f);if(key())f()}};
  (async()=>{
    try{const r=await fetch("data/destiny.json");if(!r.ok)return;const D=await r.json();N=D.nodes;(D.order||[]).forEach((n,i)=>idx[n]=String(i))}catch(e){return}
    const ls=get("aodestiny1",{});
    Object.entries(ls.lv||{}).forEach(([k,v])=>{if(+v)MAN[k]=+v});
    chr=get(K,"")||"";
    const sb=window.aoSb;
    if(sb){try{const {data:{session}}=await sb.auth.getSession();if(session){const {data,error}=await sb.from("destiny_boards").select("char,data");if(error)msg=error.message;(data||[]).forEach(r=>BOARDS[r.char]=r.data)}}catch(e){}}
    done();
    // Toplayıcı yerel ağ izni sorabilir: sadece bu bilgisayarda daha önce açılmışsa yokla
    if(get("aodps1",{}).app){
      try{const c=new AbortController();setTimeout(()=>c.abort(),2000);const r=await fetch(API+"/destiny",{cache:"no-store",signal:c.signal});if(r.ok){const j=await r.json();if(j&&j.char&&j.ts){LIVE=j;if(!get(K,""))chr=j.char;done()}}}catch(e){}
    }
  })();
})();
