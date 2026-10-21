// Discord ile giriş + bulut kayıt. Supabase ayarı yoksa ya da yüklenemezse site misafir modunda çalışır.
(function(){
  const C=window.AO_CFG||{},LS=window.localStorage;
  // Site sadece Kal Vas Flam Discord'unda "Üye" ve üstü roldekilere açık. Kontrol sunucuda (/api/access) yapılır;
  // veriler ayrıca veritabanı kurallarıyla korunur. Yerel geliştirmede (localhost) kilit yok.
  const GATE=!/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  const ACC="aoAcc",FRESH=12*3600e3,GRACE=3*86400e3;
  if(GATE){
    document.documentElement.classList.add("aolock");
    const s=document.createElement("style");
    s.textContent="html.aolock body>*:not(#aogate){display:none!important}"
      +"#aogate{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box}"
      +"#aogate .gc{max-width:420px;width:100%;text-align:center;background:var(--card,#11161d);border:1px solid var(--line,#252d38);border-radius:16px;padding:28px 22px;color:var(--ink,#e6e9ee);font:15px/1.5 Inter,system-ui,sans-serif}"
      +"#aogate h1{font-size:22px;margin:12px 0 6px}#aogate p{color:var(--mut,#8b95a3);margin:0 0 18px}#aogate .why{color:var(--warn,#d29922)}"
      +"#aogate button{font:inherit;font-weight:700;padding:10px 16px;border-radius:10px;border:1px solid #b8602a;background:var(--acc2,#7a3e16);color:var(--accT,#ffd6b3);cursor:pointer}";
    document.head.appendChild(s);
  }
  function gate(kind,why){
    if(!GATE)return;
    const go=()=>{
      let g=document.getElementById("aogate");
      if(!g){g=document.createElement("div");g.id="aogate";document.body.appendChild(g)}
      const T={
        login:["Kal Vas Flam'a özel","Bu site Kal Vas Flam Discord sunucusundaki Üye ve üstü rollere açık. Devam etmek için Discord ile giriş yap.","Discord ile giriş"],
        check:["Kontrol ediliyor","Discord rolün kontrol ediliyor…",""],
        denied:["Erişim yok","Bu site sadece Kal Vas Flam Discord sunucusundaki Üye ve üstü rollere açık. Hesabın ve bu sitedeki verilerin silindi.","Başka hesapla giriş"],
        error:["Şu an kontrol edilemiyor","Discord rolün kontrol edilemedi. Biraz sonra sayfayı yenile.","Tekrar dene"],
        off:["Giriş servisi yüklenemedi","Sayfayı yenile. Sorun sürerse internet bağlantını kontrol et.","Yenile"]}[kind];
      g.innerHTML=`<div class="gc"><img src="logo.png" alt="KVF" width="72" height="72"><h1>${T[0]}</h1><p>${T[1]}${why?`<br><span class="why">${esc(why)}</span>`:""}</p>${T[2]?`<button type="button" id="aogo">${T[2]}</button>`:""}</div>`;
      const b=document.getElementById("aogo");
      if(b)b.onclick=kind==="login"||kind==="denied"?()=>login():()=>location.reload();
    };
    document.body?go():document.addEventListener("DOMContentLoaded",go);
  }
  function unlock(){document.documentElement.classList.remove("aolock");const g=document.getElementById("aogate");if(g)g.remove()}
  const esc=t=>String(t==null?"":t).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;");
  if(!C.url||!C.key||/XXX/.test(C.url)||!window.supabase){gate("off");return}
  const sb=window.supabase.createClient(C.url,C.key,{auth:{flowType:"pkce",detectSessionInUrl:true,persistSession:true}});
  window.aoSb=sb;
  const KEYS=["aoplan3","aoplan3f","aoplan3c","aoprofiles","aoprofilesf","aoprofilesc","aoactive","aoactivef","aoactivec","aobm1","aodb1"];
  const get=k=>{try{return LS.getItem(k)}catch(e){return null}};
  const orig=Storage.prototype.setItem;
  const put=(k,v)=>{try{orig.call(LS,k,v)}catch(e){}};
  let user=null,prof={},canSync=false,timer=null,box,ann;
  const dirty=new Set();

  // Uygulama localStorage'a yazdıkça değişen anahtarları buluta gönder
  Storage.prototype.setItem=function(k,v){
    orig.call(this,k,v);
    if(this===LS&&canSync&&KEYS.includes(k)){dirty.add(k);clearTimeout(timer);timer=setTimeout(push,1500)}
  };

  function st(t,ok){const e=document.getElementById("acSt");if(e){e.textContent=t;e.style.color=ok?"var(--acc)":"var(--mut)"}}

  async function push(){
    const ks=[...dirty].filter(k=>get(k)!=null);dirty.clear();
    if(!ks.length||!canSync)return;
    const now=new Date().toISOString();
    const {error}=await sb.from("user_data").upsert(ks.map(k=>({user_id:user.id,key:k,value:get(k),updated_at:now})));
    st(error?"Buluta kaydedilemedi":"Buluta kaydedildi",!error);
  }

  // Buluttaki veriyi yerele al. Bu tarayıcıda bu hesapla ilk girişse, misafirken kaydedilen profiller de korunur.
  async function pull(){
    const {data,error}=await sb.from("user_data").select("key,value");
    if(error){st("Bulut verisi alınamadı");return false}
    const cloud=Object.fromEntries(data.map(r=>[r.key,r.value])),first=get("aoSyncUser")!==user.id;
    let changed=false;
    KEYS.forEach(k=>{
      const l=get(k),c=cloud[k];
      if(c==null){if(l!=null)dirty.add(k);return}
      let v=c;
      if(first&&/^aoprofiles/.test(k)&&l){try{v=JSON.stringify(Object.assign({},JSON.parse(l),JSON.parse(c)));if(v!==c)dirty.add(k)}catch(e){}}
      if(v!==l){put(k,v);changed=true}
    });
    put("aoSyncUser",user.id);
    await push();
    return changed;
  }

  function login(){
    try{sessionStorage.setItem("aoRet",location.hash)}catch(e){}
    // prompt=none: daha önce onay verdiyse Discord "Yetkilendir" ekranını tekrar göstermez
    sb.auth.signInWithOAuth({provider:"discord",options:{redirectTo:location.origin+location.pathname,queryParams:{prompt:"none"}}});
  }

  function render(){
    if(!user){
      box.innerHTML='<span id="acSt" class="st" style="margin:0">Misafir</span><button id="acIn">Discord ile giriş</button>';
      document.getElementById("acIn").onclick=login;
      return;
    }
    const av=prof.avatar?`<img src="${esc(prof.avatar)}" alt="" width="28" height="28" style="border-radius:50%">`:"";
    box.innerHTML=`${av}<b>${esc(prof.name||"Kullanıcı")}</b>${prof.is_admin?'<a href="/admin" style="color:var(--acc)">Panel</a>':""}<span id="acSt" class="st" style="margin:0"></span><button class="l" id="acOut">Çıkış</button>`;
    document.getElementById("acOut").onclick=async()=>{canSync=false;await sb.auth.signOut();location.reload()};
  }

  async function loadAnn(){
    const {data}=await sb.from("announcements").select("id,text").eq("active",true).order("created_at",{ascending:false}).limit(3);
    let hid=[];try{hid=JSON.parse(get("aoAnnHid")||"[]")}catch(e){}
    ann.innerHTML=(data||[]).filter(a=>!hid.includes(a.id)).map(a=>`<div class="warn" style="display:flex;gap:8px;align-items:start;border-color:var(--acc)"><span style="flex:1;white-space:pre-wrap">${esc(a.text)}</span><button class="l ic" data-an="${a.id}" aria-label="Duyuruyu kapat">✕</button></div>`).join("");
    ann.querySelectorAll("[data-an]").forEach(b=>b.onclick=()=>{hid.push(+b.dataset.an);put("aoAnnHid",JSON.stringify(hid));b.parentElement.remove()});
  }

  async function start(){
    // Giriş kutusu ortak üst menünün sağında durur (nav.js); menüsüz sayfada ilk satıra
    const row=document.getElementById("topnav")||document.querySelector("main>.row");
    if(!row)return;
    box=document.createElement("div");box.style.cssText="margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px";
    row.appendChild(box);
    ann=document.createElement("div");row.after(ann);
    loadAnn().catch(()=>{});

    const {data:{session}}=await sb.auth.getSession();
    if(new URLSearchParams(location.search).has("code"))history.replaceState(null,"",location.pathname+location.hash);
    let ret=null;try{ret=sessionStorage.getItem("aoRet");sessionStorage.removeItem("aoRet")}catch(e){}
    let reload=ret!=null&&ret!==location.hash;

    user=session&&session.user;
    if(GATE){
      if(!user){render();gate("login");return}
      let c=null;try{c=JSON.parse(get(ACC)||"null")}catch(e){}
      const mine=c&&c.uid===user.id,age=mine?Date.now()-c.ts:Infinity;
      if(age<FRESH)unlock();else gate("check");
      let a;
      try{const r=await fetch("/api/access",{headers:{Authorization:"Bearer "+session.access_token},cache:"no-store"});a=await r.json()}
      catch(e){a={allowed:null,error:"bağlantı hatası"}}
      if(a.allowed===true){put(ACC,JSON.stringify({uid:user.id,ts:Date.now()}));if(a.first&&!sessionStorage.getItem("aoFirst")){sessionStorage.setItem("aoFirst","1");location.reload();return}unlock()}
      else if(a.allowed===false){
        try{LS.removeItem(ACC);LS.removeItem("aoSyncUser")}catch(e){}
        await sb.auth.signOut().catch(()=>{});
        user=null;render();gate("denied",a.why);return;
      }
      else if(age<GRACE)unlock();
      else{render();gate("error",a.error);return}
    }
    if(user){
      const {data:p}=await sb.from("profiles").select("name,avatar,banned,is_admin").eq("id",user.id).maybeSingle();
      prof=p||{};render();
      if(prof.banned)st("Hesabın engellendi, misafir olarak devam edebilirsin");
      else{
        sb.rpc("touch").then(()=>{},()=>{});
        canSync=true;
        if(await pull())reload=true;
        else st("Bulut kayıt açık",true);
      }
    }else render();

    if(reload){if(ret!=null)location.hash=ret;location.reload()}
  }

  document.addEventListener("DOMContentLoaded",()=>start().catch(e=>{console.warn("auth",e);if(document.documentElement.classList.contains("aolock"))gate("error",String(e&&e.message||e))}));
})();
