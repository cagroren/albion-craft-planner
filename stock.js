// Depo: bankadaki ve ada sandıklarındaki malzemeler (localStorage "aostock1", Discord hesabıyla buluta eşitlenir).
// Depo sayfası yazar; Craft/Cooking/Alchemy alışveriş listesi, Refining ve Farming sadece okur.
// Yapı: {stores:{anahtar:{name, zone, kind:"bank"|"chest"|"manual", t, on, items:{eşya:adet}}}, set:{...}}
(function(){
  var K="aostock1";
  function load(){try{return JSON.parse(localStorage.getItem(K)||"{}")||{}}catch(e){return {}}}
  function save(d){try{localStorage.setItem(K,JSON.stringify(d))}catch(e){}}
  // "Hesaba kat" işaretli depoların toplamı: eşya -> adet
  function total(){
    var d=load(),t={};
    Object.keys(d.stores||{}).forEach(function(k){var s=d.stores[k];if(!s||!s.on)return;
      Object.keys(s.items||{}).forEach(function(i){t[i]=(t[i]||0)+(+s.items[i]||0)})});
    return t;
  }
  function count(){var d=load();return Object.keys(d.stores||{}).filter(function(k){return d.stores[k].on}).length}
  var f=function(n){return Math.round(n).toLocaleString("tr-TR")};
  // Plan satırlarının altına: "depoda 120 · 30 alınacak" (depoda yoksa boş)
  function tag(m,need){var h=total()[m]||0;if(!h)return "";
    var b=Math.max(0,Math.ceil(need-h-1e-9));
    return '<br><small style="color:'+(b?"#e3b341":"#3fb950")+';font-weight:600">depoda '+f(h)+" · "+(b?f(b)+" alınacak":"yeterli")+"</small>"}
  window.aoStock={K:K,load:load,save:save,total:total,count:count,tag:tag};
})();
