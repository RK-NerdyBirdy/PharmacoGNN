(() => {
  const story=document.getElementById('landingStory'),stage=document.getElementById('storyStage');
  const reduce=matchMedia('(prefers-reduced-motion: reduce)'),clamp=x=>Math.max(0,Math.min(1,x)),smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
  const intro=document.querySelector('.intro-copy'),reveal=document.querySelector('.reveal-copy'),features=document.querySelector('.story-features'),actions=document.querySelector('.intro-actions'),footer=document.querySelector('.reveal-footer');
  const dots=[...document.querySelectorAll('.spill-dots i')],numbers=[...document.querySelectorAll('.story-number')];let targets=[],raf=0;
  dots.forEach((dot,i)=>{const digit=document.createElement('span');digit.textContent=String(i+1);dot.append(digit);});
  const progress=()=>clamp(-story.getBoundingClientRect().top/Math.max(1,story.offsetHeight-stage.offsetHeight));
  function measure(){const box=stage.getBoundingClientRect();targets=numbers.map(n=>{const r=n.getBoundingClientRect();return {x:r.left-box.left,y:r.top-box.top,w:r.width,h:r.height};});}
  function render(){raf=0;const p=reduce.matches?1:progress(),open=smooth((p-.12)/.58),a=1-smooth(p/.35),b=smooth((p-.25)/.3),cards=smooth((p-.58)/.3),part=smooth((p-.08)/.78),waveFade=1-smooth((p-.61)/.3);stage.dataset.progress=p.toFixed(3);stage.style.setProperty('--open',open);stage.style.setProperty('--intro',a);stage.style.setProperty('--reveal',b);stage.style.setProperty('--cards',cards);stage.style.setProperty('--wave-part',part);stage.style.setProperty('--wave-fade',waveFade);stage.style.setProperty('--graph-turn',open*38);intro.inert=a<.1;intro.setAttribute('aria-hidden',a<.1);actions.inert=a<.1;actions.style.pointerEvents=a<.1?'none':'auto';reveal.setAttribute('aria-hidden',b<.1);features.inert=cards<.6;features.setAttribute('aria-hidden',cards<.6);footer.inert=cards<.6;footer.setAttribute('aria-hidden',cards<.6);
    const mobile=innerWidth<=600,startX=stage.clientWidth/2,startY=stage.clientHeight*(mobile?.43:.49);
    dots.forEach((dot,i)=>{const t=targets[i];if(!t)return;const travel=smooth((p-.38-i*.025)/(.5-i*.025));const x=startX+(t.x+t.w/2-startX)*travel+Math.sin(travel*Math.PI)*(i<2?-30:30);const y=startY+(t.y+t.h/2-startY)*travel-Math.sin(travel*Math.PI)*(55+i*12);dot.style.width=t.w+'px';dot.style.height=t.h+'px';dot.style.transform='translate('+(x-t.w/2)+'px,'+(y-t.h/2)+'px) scale('+(.4+.6*travel)+')';dot.style.opacity=smooth((p-.38-i*.025)/.1);dot.style.setProperty('--digit',smooth((travel-.94)/.06));});
  }
  const schedule=()=>{if(!raf)raf=requestAnimationFrame(render);};addEventListener('scroll',schedule,{passive:true});addEventListener('resize',()=>{measure();schedule();});reduce.addEventListener('change',()=>{measure();schedule();});
  document.querySelectorAll('[data-reveal]').forEach(b=>b.onclick=()=>window.scrollTo({top:story.offsetTop+story.offsetHeight-stage.offsetHeight,behavior:reduce.matches?'instant':'smooth'}));
  const chars=[];document.querySelectorAll('.headline-line').forEach(line=>{const text=line.textContent;line.textContent='';[...text].forEach(c=>{const span=document.createElement('span');span.className='headline-letter';span.textContent=c;line.append(span);chars.push(span);});});
  const headline=document.getElementById('landingHeadline'),proximity=100;
  headline.addEventListener('pointermove',event=>{if(reduce.matches||progress()>.15)return;chars.forEach(char=>{const r=char.getBoundingClientRect(),distance=Math.hypot(r.left+r.width/2-event.clientX,r.top+r.height/2-event.clientY),amount=Math.max(0,1-distance/proximity);char.style.fontVariationSettings="'wght' "+Math.round(400+amount*600)+", 'opsz' "+Math.round(9+amount*31);});});
  headline.addEventListener('pointerleave',()=>chars.forEach(char=>{char.style.fontVariationSettings="'wght' 400, 'opsz' 9";}));
  measure();render();document.fonts.ready.then(()=>{measure();render();});
})();
