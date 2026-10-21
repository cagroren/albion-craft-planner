// Discord ile giriş + bulut kayıt. Supabase ayarı yoksa ya da yüklenemezse site misafir modunda çalışır.
(function(){
  const C=window.AO_CFG||{},LS=window.localStorage;
  if(!C.url||!C.key||/XXX/.test(C.url)||!window.supabase)return;
  const sb=window.supabase.createClient(C.url,C.key,{auth:{flowType:"pkce",detectSessionInUrl:true,persistSession:true}});
  window.aoSb=sb;
  const KEYS=["aoplan3","aoplan3f","aoplan3c","aoprofiles","aoprofilesf","aoprofilesc","aoactive","aoactivef","aoactivec","aobm1","aodb1"];
  const esc=t=>String(t==null?"":t).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;");
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
    sb.auth.signInWithOAuth({provider:"discord",options:{redirectTo:location.origin+location.pathname}});
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

  document.addEventListener("DOMContentLoaded",()=>start().catch(e=>console.warn("auth",e)));
})();
