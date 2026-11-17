nameCard('Humaira Shah','Nutrition Scientist (MSc)',.35,5.4);
// INTRO: NHS + 30g
chip('NHS',540,330,.36,2.6,'chip',{fontSize:'44px',padding:'10px 30px',background:'#1F4D3A',color:'#FAF6EC',borderColor:'#B08D57'});
(function(){const e=el('big','');e.style.fontSize='150px';items.push(t=>{const t0=1.15,t1=2.95;const s=life(t,t0,t1,.3);const v=Math.round(30*eo((t-t0)/.55));e.innerHTML=v+'g<span style="font-size:46px;font-family:Inter;font-weight:800;letter-spacing:3px"> A DAY</span>';setT(e,540,470,s,0,s>0?1:0)})})();
chip('Source: NHS',870,1240,1.2,6.2,'lbl',{fontSize:'20px',letterSpacing:'2px'});
// row A (allowance) appears on "seven sugar cubes"
chip("today's sugar: 7 cubes",540,262,4.25,19.3,'lbl');
window.TARGETS=[[8.0,12.5,170],[12.72,15.4,900],[15.55,17.85,170],[17.86,20.0,900]];
cubeRow(350,7,{appear:[4.45,4.52,4.59,4.66,4.73,4.80,4.87],knock:[10.8,10.95,14.0,14.12,14.24,15.62,19.4],end:23.45});
// verse 1 stickers
sticker('🥣',150,170,560,8.0,12.5,{script:[[8.0,'wave'],[9.2,'smug',{halo:1}],[10.75,'busted',{halo:1,hdy:7,hrot:-25}],[11.6,'whistle']],geo:{fx:50,fy:68,fs:.72,ax:6,axr:94,ay:64,ly:86,ll:14}});chip('about ⅓ of your day',300,690,10.75,12.6,'chip',{fontSize:'28px'});
sticker('🍊',140,900,560,12.72,15.4,{script:[[12.72,'wave'],[13.4,'dance'],[14.0,'shock'],[14.6,'worried']],geo:{fy:58,fs:.75}});chip('≈ 13g',900,690,14.0,15.4,'chip');
sticker('🍅',140,170,560,15.55,17.85,{script:[[15.55,'tiptoe']],geo:{fy:60,fs:.75}});chip('hidden sugar',230,690,15.9,17.85,'chip',{fontSize:'28px'});
sticker('🍫',140,900,560,17.86,20.0,{script:[[17.86,'run']],geo:{fy:52,fs:.72}});chip('hidden sugar',850,690,18.3,20.0,'chip',{fontSize:'28px'});
sticker('☕',160,190,560,20.0,23.35,{script:[[20.0,'sleepy'],[21.2,'idle'],[22.5,'think']],geo:{fx:44,fy:60,fs:.72,axr:84,ay:62}});chip('+ syrup',240,690,20.6,23.35,'chip');
chip('all gone',540,262,19.45,23.3,'lbl',{background:'#C2553B',color:'#FAF6EC'});
// WAIT
(function(){const e=el('big','wait.');e.style.fontSize='190px';e.style.fontStyle='italic';e.style.color='#C2553B';items.push(t=>{const t0=23.48,t1=24.85;if(t<t0||t>t1+.15){setT(e,540,430,0,0,0);return}const k=(t-t0)/.14;const s=k<1?2.4-1.4*eo(k):1;const sh=t<t0+.5?Math.sin(t*90)*8:0;setT(e,540+sh,430,s,-4,t>t1?1-(t-t1)/.15:1)})})();
sticker('⏸️',110,880,300,23.5,24.8);
// CHORUS 1
chip('7 cubes = your whole day',540,262,24.9,27.4,'lbl');
cubeRow(350,7,{appear:[24.95,25.15,25.35,25.55,25.75,25.95,26.4],knock:[27.5,27.55,27.6,27.65,27.7,27.75,27.8],end:28.6,drop:true});
sticker('🕛',150,540,420,28.0,29.55,{script:[[28.0,'tap']],geo:{fy:64,fs:.6}});chip('lunch',540,535,28.05,29.55,'chip');
['❓','❔','❓'].forEach((q,i)=>sticker(q,90,[230,850,700][i],[420,380,560][i],28.6+i*.1,29.6,{dy:t=>-Math.abs(Math.sin((t-28.6)*8+i))*30}));
sticker('🍪',140,190,520,29.7,31.7,{script:[[29.7,'wave'],[30.4,'sad']],geo:{fy:52,fs:.72}});
sticker('🍬',140,890,520,31.1,31.75,{script:[[31.1,'sad']],geo:{fy:50,fs:.55,ax:16,axr:84}});
(function(){[[190,520,30.4],[890,520,31.6]].forEach(([x,y,t0])=>{const e=el('a','<svg width="170" height="170" viewBox="0 0 170 170"><circle cx="85" cy="85" r="70" fill="none" stroke="#C2553B" stroke-width="12"/><line x1="36" y1="134" x2="134" y2="36" stroke="#C2553B" stroke-width="12" stroke-linecap="round"/></svg>');items.push(t=>{const t1=t0<31?31.7:31.75;const s=life(t,t0,t1,.2);setT(e,x,y,s,0,s>0?1:0)})})})();
chip('skipped',190,660,30.45,31.7,'chip',{fontSize:'28px'});chip('skipped',890,660,31.15,31.75,'chip',{fontSize:'28px'});
sticker('🥣',150,330,500,31.8,33.95,{script:[[31.8,'angel'],[33.3,'busted',{halo:1,hdy:14,hrot:-30}]],geo:{fx:50,fy:68,fs:.72,ax:6,axr:94,ay:64,ly:86,ll:14}});sticker('🍓',130,750,500,32.0,33.95,{script:[[32.0,'angel'],[33.3,'whistle']],geo:{fy:60,fs:.65}});
chip('"healthy-looking"',540,660,32.9,33.95,'chip',{fontSize:'32px',rot:-3});

// VERSE 2: cola
sticker('🥤',220,880,560,34.0,39.1,{script:[[34.0,'flex'],[35.75,'laugh'],[37.3,'flex']],geo:{fx:46,fy:62,fs:.78,ax:18,axr:80,ay:60,ly:94}});
(function(){const e=el('big','');e.style.fontSize='130px';items.push(t=>{const t0=35.75,t1=39.1;const s=life(t,t0,t1,.3);const v=Math.round(53*eo((t-t0)/.7));e.innerHTML=v+'g';setT(e,280,560,s,0,s>0?1:0)})})();
chip('500ml cola',280,665,34.8,39.1,'chip',{fontSize:'28px'});
chip('day 1',150,262,36.0,39.1,'lbl');chip('day 2',150,375,37.25,39.1,'lbl');
(function(){const n1=7,n2=6,C=70,G=12;const sx=270;const mk=(row,i,t0)=>{const c=el('cube','');c.style.width=c.style.height=C+'px';const LF=mkLife(c,{fx:50,fy:47,fs:1.05,ax:-1,axr:101,ay:62,al:.8,lx:32,lxr:68,ly:100,ll:12});items.push(t=>{if(t<t0||t>39.35)return;let p=t<t0+.35?BH('flail',t,i+row*7):(t>=37.3&&t<38.0?BH('shock',t,i):BH(row?'worried':'idle',t,i+row*7));if(!row&&t<37.3)p.look=[clamp((880-(sx+i*(C+G)))/300,-1,1),.3];drawLife(LF,p)});const x=sx+i*(C+G),y=row?375:262;items.push(t=>{if(t<t0||t>39.35){setT(c,x,y,0,0,0);return}const k=(t-t0)/.3;const yy=k<1?y-220*(1-eo(k)):y+(t-t0-.3<.15?-Math.sin((t-t0-.3)/.15*Math.PI)*10:0);setT(c,x,yy,1,0,t>39.1?1-(t-39.1)/.25:clamp(k*3))})};
for(let i=0;i<n1;i++)mk(0,i,35.95+i*.07);for(let i=0;i<n2;i++)mk(1,i,36.6+i*.09)})();
stamp('NEARLY 2 DAYS',600,470,37.3,39.1,-7);
// survey + double
sticker('📋',140,170,430,39.2,44.0,{script:[[39.2,'think'],[41.05,'shock'],[41.6,'worried']],geo:{fy:62,fs:.7}});chip('national diet survey',300,560,39.5,44.0,'chip',{fontSize:'26px'});
bigtxt('2×',190,780,400,41.05,44.0,'#C2553B');
chip('UK adults vs the limit',780,535,41.2,44.0,'chip',{fontSize:'26px'});
['🧕🏽','👨🏾','👩🏻','🧔🏽','👵🏼'].forEach((p,i)=>sticker(p,86,190+i*175,690,41.6+i*.12,44.0,{dx:t=>t>43.5&&t<44?Math.sin(t*70+i)*6:0}));
chip('Source: NDNS 2019 to 2023',800,1240,39.4,44.0,'lbl',{fontSize:'20px',letterSpacing:'2px'});
// BRIDGE good news
chip('✨ good news ✨',540,300,44.06,48.7,'chip',{fontSize:'40px',background:'#3E8E5E',color:'#FAF6EC',borderColor:'#FAF6EC'});
sticker('🍌',140,170,500,46.3,50.9,{script:[[46.3,'wave'],[47.0,'dance']],geo:{fy:56,fs:.7}});sticker('🍎',110,300,560,46.6,50.9,{script:[[46.6,'dance']],geo:{fy:60,fs:.65}});
sticker('🥛',150,890,520,47.5,50.9,{script:[[47.5,'wave'],[48.2,'dance']],geo:{fy:62,fs:.7}});
chip("✓ doesn't count",250,680,48.1,50.9,'chip',{fontSize:'28px',color:'#3E8E5E',borderColor:'#3E8E5E'});
chip("✓ doesn't count",870,680,48.45,50.9,'chip',{fontSize:'28px',color:'#3E8E5E',borderColor:'#3E8E5E'});
chip('free sugars',540,300,48.86,55.0,'chip',{fontSize:'38px',background:'#C2553B',color:'#FAF6EC',borderColor:'#FAF6EC'});
(function(){const adds=[51.2,51.8,53.0,53.6];const C=74;adds.forEach((t0,j)=>{[0,1].forEach(side=>{const c=el('cube','');c.style.width=c.style.height=C+'px';const x=side?900:180,y=700-j*(C+8);const ts=t0+side*.08;const LF=mkLife(c,{fx:50,fy:47,fs:1.05,ax:-1,axr:101,ay:62,al:.8,lx:32,lxr:68,ly:100,ll:11});items.push(t=>{if(t<ts||t>55.25)return;const above=adds.filter((a,k)=>k>j&&t>=a+.25).length;let p=t<ts+.6?BH('cheer',t,j*2+side):(above>0?BH('squish',t,j):BH('idle',t,j*2+side));if(above>0){p.fsc=1;p.bob=Math.min(4,above*1.5)}drawLife(LF,p)});items.push(t=>{if(t<ts||t>55.25){setT(c,x,y,0,0,0);return}const k=(t-ts)/.25;const yy=k<1?y-200*(1-eo(k)):y;setT(c,x,yy,1,0,t>55?1-(t-55)/.25:clamp(k*3))})})});
chip('adds up',540,430,51.2,55.0,'big',{fontSize:'96px',color:'#C2553B'})})();
// FINAL CHORUS swaps
function swap(t0,t1,L,Ltxt,R,Rtxt,extra){const c=el('card','');c.style.width='860px';c.style.height='300px';
 c.innerHTML=`<div style="position:absolute;left:30px;top:20px;width:260px;text-align:center"><div class="emo se" style="display:inline-block;width:130px;height:130px;position:relative;font-size:118px;line-height:130px;filter:none">${L}</div><div style="font-family:Inter;font-weight:800;font-size:28px;color:#8a6a3a;margin-top:8px">${Ltxt}</div></div>
 <svg style="position:absolute;left:300px;top:70px" width="260" height="120" viewBox="0 0 260 120"><path class="ar" d="M20 60 C 90 10, 170 10, 230 60" fill="none" stroke="#B08D57" stroke-width="12" stroke-linecap="round" stroke-dasharray="260" stroke-dashoffset="260"/><path class="ah" d="M205 35 L232 62 L198 78" fill="none" stroke="#B08D57" stroke-width="12" stroke-linecap="round" stroke-linejoin="round" opacity="0"/></svg>
 <div style="position:absolute;left:570px;top:20px;width:260px;text-align:center"><div class="emo se" style="display:inline-block;width:130px;height:130px;position:relative;font-size:118px;line-height:130px;filter:none">${R}</div><div style="font-family:Inter;font-weight:800;font-size:28px;color:#1F4D3A;margin-top:8px">${Rtxt}</div></div>
 <div style="position:absolute;left:316px;top:-26px;width:230px;text-align:center;font-family:Inter;font-weight:900;font-size:24px;letter-spacing:4px;color:#FAF6EC;background:#1F4D3A;border-radius:20px;padding:8px 0">SWAP</div>${extra||''}`;
 const ar=c.querySelector('.ar'),ah=c.querySelector('.ah'),tk=c.querySelector('.tk');const ses=c.querySelectorAll('.se');const LLf=mkLife(ses[0],{fs:.62,fy:56,ll:12}),LRf=mkLife(ses[1],{fs:.62,fy:56,ll:12});items.push(t=>{if(t<t0-.05||t>t1+.3)return;drawLife(LLf,BH(t<t0+.5?'shock':'sad',t,3));drawLife(LRf,BH(t<t0+.7?'wave':'cheer',t,5))});
 items.push(t=>{if(t<t0-.05||t>t1+.3){c.style.opacity=0;c.style.display='none';return}c.style.display='block';const s=t<t0+.3?back((t-t0)/.3):1;const xo=t>t1?-1100*ei((t-t1)/.3):0;c.style.opacity=1;c.style.transform=`translate(${110+xo}px,${280}px) scale(${s})`;c.style.transformOrigin='430px 150px';const k=eo((t-t0-.2)/.4);ar.style.strokeDashoffset=260*(1-k);ah.style.opacity=k>.95?1:0;if(tk)tk.style.opacity=t>t0+.5?1:0})}
swap(55.4,57.6,'🍨','flavoured yoghurt','🥣','plain + fruit','<div class="emo tk" style="position:absolute;left:760px;top:10px;font-size:70px;opacity:0">🫐</div>');
swap(57.65,59.05,'🥣','granola','🌾','porridge');
swap(59.1,60.25,'🧃','juice','💧','water');
swap(60.3,62.55,'🥤','full-sugar fizz','🥤','sugar-free','<div style="position:absolute;left:740px;top:24px;font-family:Inter;font-weight:900;font-size:36px;color:#FAF6EC;background:#3E8E5E;border-radius:30px;padding:4px 14px">0g</div>');
swap(62.6,63.85,'🍅','all the sauce','🍅','half','<div style="position:absolute;left:745px;top:20px;font-family:Fraunces;font-weight:900;font-size:60px;color:#1F4D3A">½</div>');

confetti([63.95,64.95]);
shareCTA(63.95,65.25,'Send this to the friend who thinks their granola is <i style="color:#C2553B">health food</i> <span class="emo" style="filter:none">🥣</span>');

// camera for this song (times are in song time for this example; new songs use raw-video time)
window.ZOOM=function(t){let z=1.0;
 if(t<2.85)z=1.03+0.05*eio(t/2.85); else if(t<6.0)z=1.08+0.04*eio((t-2.85)/.5);
 else if(t<8)z=1.0; else if(t<17.86)z=1.02+0.02*((t-8)/9.86);
 else if(t<23.48)z=1.03+0.1*eio((t-17.86)/5.6);
 else if(t<24.9)z=1.3; else if(t<34)z=1.0+0.025*beatPulse(t,24.94,33.9);
 else if(t<44.06){z=1.04; if(t>37.3&&t<39.2)z=1.13; if(t>41.05&&t<44.06)z=1.1}
 else if(t<55.06)z=1.02+0.03*((t-44.06)/11);
 else if(t<65.5)z=1.0+0.025*beatPulse(t,55.06,65.4);
 else z=1.0+0.04*eio((t-65.5)/3);
 return z}
window.SHAKES=[[23.48,.45,14],[37.3,.25,8],[41.05,.25,8],[27.5,.3,6]];
window.FLASHES=[23.48,24.94,55.06];
window.GLITCH=[[23.48,.5]];
