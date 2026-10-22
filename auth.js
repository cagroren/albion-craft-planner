// Discord ile giriş + bulut kayıt. Supabase ayarı yoksa ya da yüklenemezse site misafir modunda çalışır.
(function(){
  const C=window.AO_CFG||{},LS=window.localStorage;
  // Site sadece Kal Vas Flam Discord'unda "Üye" rolü olanlara açık. Kontrol sunucuda (/api/access) yapılır;
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
        login:["Kal Vas Flam'a özel","Bu site Kal Vas Flam Discord sunucusunda Üye rolü olanlara açık. Devam etmek için Discord ile giriş yap.","Discord ile giriş"],
        check:["Kontrol ediliyor","Discord rolün kontrol ediliyor…",""],
        denied:["Erişim yok","Bu site sadece Kal Vas Flam Discord sunucusunda Üye rolü olanlara açık. Hesabın ve bu sitedeki verilerin silindi.","Başka hesapla giriş"],
        error:["Şu an kontrol edilemiyor","Discord rolün kontrol edilemedi. Biraz sonra sayfayı yenile.","Tekrar dene"],
        closed:["Bu sekme şu an kapalı","Yöneticiler bu sekmeyi geçici olarak kapattı. Diğer sekmeleri kullanmaya devam edebilirsin.","Ana sayfaya dön"],
        off:["Giriş servisi yüklenemedi","Sayfayı yenile. Sorun sürerse internet bağlantını kontrol et.","Yenile"]}[kind];
      g.innerHTML=`<div class="gc"><img src="logo.png" alt="KVF" width="72" height="72"><h1>${T[0]}</h1><p>${T[1]}${why?`<br><span class="why">${esc(why)}</span>`:""}</p>${T[2]?`<button type="button" id="aogo">${T[2]}</button>`:""}</div>`;
      const b=document.getElementById("aogo");
      if(b)b.onclick=kind==="login"||kind==="denied"?()=>login():kind==="closed"?()=>{location.assign(window.aoNav?window.aoNav.home():"/");setTimeout(()=>location.reload(),50)}:()=>location.reload();
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

  async function access(session){
    try{const r=await fetch("/api/access",{headers:{Authorization:"Bearer "+session.access_token},cache:"no-store"});return await r.json()}
    catch(e){return {allowed:null,error:"bağlantı hatası"}}
  }
  // Erişim kesin olarak yok: çıkış yapılır; oturum sadece süresi dolmuşsa giriş ekranı, değilse "erişim yok"
  async function shut(a){
    try{LS.removeItem(ACC);LS.removeItem("aoSyncUser")}catch(e){}
    canSync=false;
    await sb.auth.signOut().catch(()=>{});
    user=null;render();
    document.documentElement.classList.add("aolock");
    a.session?gate("login"):gate("denied",a.why);
  }

  // Sağ altta geri bildirim balonu: başlık + açıklama, sadece site sahibi panelde görür
  function feedbackUI(){
    if(document.getElementById("fbBtn"))return;
    const s=document.createElement("style");
    s.textContent="#fbBtn{position:fixed;right:16px;bottom:16px;z-index:50;display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:22px 22px 6px 22px;border:1px solid #b8602a;background:var(--acc2,#7a3e16);color:var(--accT,#ffd6b3);font:700 14px/1 Inter,system-ui,sans-serif;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.35)}"
      +"#fbBtn:hover{background:#8f4a1b;border-color:var(--acc,#f0883e)}#fbBtn svg{width:18px;height:18px}"
      +"#fbBox{position:fixed;right:16px;bottom:72px;z-index:51;width:min(380px,calc(100vw - 32px));background:var(--card,#11161d);border:1px solid var(--line2,#323c49);border-radius:14px;padding:16px;box-shadow:0 12px 32px rgba(0,0,0,.45);font:14px/1.5 Inter,system-ui,sans-serif;color:var(--ink,#e6e9ee)}"
      +"#fbBox h3{margin:0 0 4px;font-size:16px}#fbBox p{margin:0 0 12px;color:var(--mut,#8b95a3);font-size:13px}"
      +"#fbBox label{display:block;font-size:12px;font-weight:600;color:#c3cad4;margin:10px 0 4px}"
      +"#fbBox input,#fbBox textarea{width:100%;box-sizing:border-box;font:inherit;padding:9px 12px;border:1px solid var(--line2,#323c49);border-radius:9px;background:var(--in,#0d1218);color:var(--ink,#e6e9ee)}#fbBox textarea{resize:vertical;min-height:110px}"
      +"#fbBox .r{display:flex;gap:8px;align-items:center;margin-top:12px}#fbBox .r span{flex:1;font-size:13px;color:var(--mut,#8b95a3)}"
      +"#fbBox button{font:inherit;font-weight:700;padding:8px 14px;border-radius:9px;border:1px solid #b8602a;background:var(--acc2,#7a3e16);color:var(--accT,#ffd6b3);cursor:pointer}#fbBox button.l{background:transparent;color:var(--acc,#f0883e);border-color:#5a3a24}"
      +"@media print{#fbBtn,#fbBox{display:none}}";
    document.head.appendChild(s);
    const b=document.createElement("button");b.id="fbBtn";b.type="button";b.setAttribute("aria-expanded","false");
    b.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>Feedback';
    document.body.appendChild(b);
    let box=null;
    const close=()=>{if(box){box.remove();box=null}b.setAttribute("aria-expanded","false")};
    b.onclick=()=>{
      if(box)return close();
      box=document.createElement("div");box.id="fbBox";box.setAttribute("role","dialog");box.setAttribute("aria-label","Geri bildirim");
      box.innerHTML='<h3>Geri bildirim gönder</h3><p>Hata, öneri ya da istek yaz; doğrudan site sahibine gider.</p><label for="fbT">Başlık</label><input id="fbT" maxlength="100" placeholder="Kısaca konu"><label for="fbD">Açıklama</label><textarea id="fbD" maxlength="2000" placeholder="Ne oldu, ne istiyorsun? Hangi sekmede?"></textarea><div class="r"><span id="fbS"></span><button type="button" class="l" id="fbX">Vazgeç</button><button type="button" id="fbGo">Gönder</button></div>';
      document.body.appendChild(box);b.setAttribute("aria-expanded","true");
      document.getElementById("fbT").focus();
      document.getElementById("fbX").onclick=close;
      box.addEventListener("keydown",e=>{if(e.key==="Escape"){close();b.focus()}});
      document.getElementById("fbGo").onclick=async()=>{
        const t=document.getElementById("fbT").value.trim(),d=document.getElementById("fbD").value.trim(),S=document.getElementById("fbS"),g=document.getElementById("fbGo");
        if(!t){S.textContent="Önce bir başlık yaz.";document.getElementById("fbT").focus();return}
        g.disabled=true;S.textContent="Gönderiliyor…";
        const {error}=await sb.from("feedback").insert({title:t,body:d||null,page:(window.aoNav&&window.aoNav.page)||location.pathname});
        g.disabled=false;
        if(error){S.textContent="Gönderilemedi: "+error.message;return}
        box.innerHTML='<h3>Teşekkürler!</h3><p style="margin:0">Geri bildirimin site sahibine ulaştı.</p>';
        setTimeout(close,2500);
      };
    };
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
      const a=await access(session);
      if(a.allowed===true){put(ACC,JSON.stringify({uid:user.id,ts:Date.now()}));if(a.first&&!sessionStorage.getItem("aoFirst")){sessionStorage.setItem("aoFirst","1");location.reload();return}unlock()}
      else if(a.allowed===false){await shut(a);return}
      else if(age<GRACE)unlock();
      else{render();gate("error",a.error);return}
      // Açık sayfada da 2 dakikada bir bakılır: Discord'dan atılan kişinin sayfası hemen kilitlenir
      setInterval(async()=>{
        const {data:{session:s}}=await sb.auth.getSession();
        if(!s){location.reload();return}
        const b=await access(s);
        if(b.allowed===false)await shut(b);
      },120e3);
    }
    if(user){
      const {data:p}=await sb.from("profiles").select("name,avatar,banned,is_admin").eq("id",user.id).maybeSingle();
      prof=p||{};render();
      // Panelden kapatılan sekmeler: menüden gizlenir, kapalı sayfa açılırsa uyarı (adminler girebilir)
      sb.from("site_settings").select("value").eq("key","tabs_off").maybeSingle().then(({data})=>{
        const off=Array.isArray(data&&data.value)?data.value:[];
        if(!window.aoNav)return;
        window.aoNav.set(off,prof.is_admin);
        if(off.includes(window.aoNav.page)&&!prof.is_admin){document.documentElement.classList.add("aolock");gate("closed")}
      },()=>{});
      if(prof.banned)st("Hesabın engellendi, misafir olarak devam edebilirsin");
      else{
        sb.rpc("touch").then(()=>{},()=>{});
        feedbackUI();
        // Panel istatistikleri için sayfa açılışı (ana sayfada sekme: #craft, #farm...)
        const pg=location.pathname.replace(/^\/|\.html$/g,"").replace(/^index$/,"")||"#"+(location.hash.slice(1).split(/[=&]/)[0]||"alchemy");
        sb.rpc("track",{p:pg}).then(()=>{},()=>{});
        canSync=true;
        if(await pull())reload=true;
        else st("Bulut kayıt açık",true);
      }
    }else render();

    if(reload){if(ret!=null)location.hash=ret;location.reload()}
  }

  document.addEventListener("DOMContentLoaded",()=>start().catch(e=>{console.warn("auth",e);if(document.documentElement.classList.contains("aolock"))gate("error",String(e&&e.message||e))}));
})();
