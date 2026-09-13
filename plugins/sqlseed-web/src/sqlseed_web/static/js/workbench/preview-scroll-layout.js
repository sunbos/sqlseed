/** Keep one vertical scroll owner; the table stays intact for column alignment. */
export function createPreviewScrollLayout({dialog,results,inline=false}) {
  const {el,body}=dialog;
  let table=null,closed=false,frame=null;
  const number=value=>Number.parseFloat(value)||0;
  const outerHeight=node=>{
    const style=getComputedStyle(node);
    return node.getBoundingClientRect().height+number(style.marginTop)+number(style.marginBottom);
  };
  function captureVertical() {
    if(closed || inline || !table || typeof getComputedStyle!=='function')return null;
    // Store one position per table, independent of the current scroll owner.
    // A body's migrated table offset must not also become shared tab state.
    return {tableTop:(table.scrollTop||0)+(body.scrollTop||0),bodyTop:0};
  }
  function restoreVertical(tableTop=0,bodyTop=0) {
    if(closed || inline || !table || typeof getComputedStyle!=='function')return;
    const ownScroll=el.classList.contains('wb-preview-table-scroll');
    const position=tableTop+bodyTop;
    body.scrollTop=ownScroll?0:position;
    table.scrollTop=ownScroll?position:0;
  }
  function update(preserve=true) {
    if(closed || inline || !table || !el.isConnected || typeof getComputedStyle!=='function')return;
    const modalStyle=getComputedStyle(el),bodyStyle=getComputedStyle(body),resultStyle=getComputedStyle(results);
    // Use the modal's allowed height, not its current content height, so changing
    // the scroll owner cannot make this measurement oscillate.
    const bodyHeight=number(modalStyle.maxHeight)
      -number(modalStyle.paddingTop)-number(modalStyle.paddingBottom)
      -number(modalStyle.borderTopWidth)-number(modalStyle.borderBottomWidth)
      -[...el.children].filter(node=>node!==body).reduce((height,node)=>height+outerHeight(node),0)
      -number(bodyStyle.marginTop)-number(bodyStyle.marginBottom)
      -number(bodyStyle.borderTopWidth)-number(bodyStyle.borderBottomWidth);
    const above=table.getBoundingClientRect().top-body.getBoundingClientRect().top+(body.scrollTop||0)-(body.clientTop||0);
    const below=number(bodyStyle.paddingBottom)+number(resultStyle.paddingBottom)
      +number(resultStyle.borderBottomWidth)+number(resultStyle.marginBottom);
    const available=Math.floor(bodyHeight-above-below);
    const header=table.querySelector('thead');
    const rows=[...(table.querySelector('tbody')?.children || [])].slice(0,3);
    const minimum=(header?.getBoundingClientRect().height || 0)
      +rows.reduce((height,row)=>height+row.getBoundingClientRect().height,0)
      +table.offsetHeight-table.clientHeight;
    const width=document.documentElement?.clientWidth || innerWidth;
    // Without size observation a later error could overflow a fixed body.
    const ownScroll=Boolean(observer && width>600 && minimum>0 && available>=minimum);
    const changed=el.classList.contains('wb-preview-table-scroll')!==ownScroll;
    const position=(body.scrollTop||0)+(table.scrollTop||0);
    const limit=ownScroll?`${available}px`:'';
    if(table.style.maxHeight!==limit)table.style.maxHeight=limit;
    el.classList.toggle('wb-preview-table-scroll',ownScroll);
    if(changed && preserve) {
      // A resize may change owners without rebuilding the preview. Carry its
      // vertical offset across instead of letting the old owner clamp it to 0.
      restoreVertical(position);
    }
  }
  function schedule() {
    if(closed || frame!==null)return;
    if(typeof requestAnimationFrame!=='function'){update();return;}
    frame=requestAnimationFrame(()=>{frame=null;update();});
  }
  const observer=!inline && typeof ResizeObserver!=='undefined'?new ResizeObserver(schedule):null;
  function setTable(node) {
    if(closed)return;
    if(table && table!==node)table.style.maxHeight='';
    table=node;
    observer?.disconnect();
    if(inline) {
      table?.classList.toggle('wb-preview-long',(table.querySelector('tbody')?.children.length || 0)>10);
      return;
    }
    el.classList.remove('wb-preview-table-scroll');
    if(!table)return;
    // Direct children include status, errors and wrapping table tabs. Observe
    // their actual heights as well as the rows used for the readable minimum.
    for(const node of [el,...el.children,...body.children,table.querySelector('thead'),
      ...[...(table.querySelector('tbody')?.children || [])].slice(0,3)]) {
      if(node)observer?.observe(node);
    }
    update(false);
  }
  if(!inline)window.addEventListener('resize',schedule);
  function destroy() {
    closed=true;
    observer?.disconnect();
    if(frame!==null)cancelAnimationFrame(frame);
    frame=null;
    if(!inline)window.removeEventListener('resize',schedule);
    if(table)table.style.maxHeight='';
    el.classList.remove('wb-preview-table-scroll');
    table=null;
  }
  return {setTable,update,captureVertical,restoreVertical,destroy};
}
