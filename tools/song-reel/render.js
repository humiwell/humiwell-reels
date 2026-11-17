const {chromium}=require('playwright');
(async()=>{const [,,a,b,step,outdir]=process.argv;const S=+a,E=+b,ST=+(step||1),OD=outdir||'frames';
const br=await chromium.launch({args:['--allow-file-access-from-files']});
const pg=await br.newPage({viewport:{width:1080,height:1920}});
pg.on('pageerror',e=>console.error('PAGEERR',e.message));
await pg.goto('file://'+process.cwd()+'/comp.html');await pg.evaluate(()=>document.fonts.ready);
await pg.evaluate(async()=>{await document.fonts.load('900 50px Fraunces');await document.fonts.load('700 50px Fraunces');await document.fonts.load('italic 700 50px Fraunces');await document.fonts.load('800 50px Inter');await document.fonts.load('900 50px Inter');await document.fonts.load('600 50px Inter');});
const fs=require('fs');fs.mkdirSync(OD,{recursive:true});
for(let i=S;i<E;i+=ST){await pg.evaluate(i=>window.renderFrame(i),i);await pg.screenshot({path:`${OD}/${String(i).padStart(5,'0')}.jpg`,type:'jpeg',quality:90});}
await br.close()})();
