// Chart presentations share the exact input values; changing type never calls an API.
(()=>{
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const preferences=Object.create(null);
 const storageKey='sigi-chart-types:'+(globalThis.SIGI_CONTEXT?.basePath||'');
 try{Object.assign(preferences,JSON.parse(sessionStorage.getItem(storageKey)||'{}'))}catch{}
 const format=(value,unit)=>new Intl.NumberFormat('pt-BR',unit==='number'?{maximumFractionDigits:2}:{style:'currency',currency:'BRL'}).format(value);
 function types(rows,options){return [['original','Gráfico atual'],['bars','Barras'],['columns','Colunas'],['line','Linhas'],...(options.share&&rows.every(row=>row.value>=0)?[['donut','Rosca']]:[]),['table','Tabela']]}
 function normalize(rows){return rows.map(row=>({label:String(row.label??''),value:Number.isFinite(Number(row.value))?Number(row.value):0,color:['b','g','o','r','mute','y'].includes(row.color)?row.color:'b'}))}
 function sectorColor(id){let number=Number(id);if(id==null||!Number.isFinite(number)){number=0;for(const c of String(id??'none'))number=(number*31+c.charCodeAt(0))>>>0}const hue=((number+1)*137.508)%360;return `light-dark(hsl(${hue} 68% 39%),hsl(${hue} 68% 68%))`}
 function sectorLines(source,labels,valueOf){const groups=new Map();for(const row of source){const key=row.department_id==null?'none':String(row.department_id);if(!groups.has(key))groups.set(key,{id:key,label:row.department||row.name||(key==='none'?'Sem setor':'Setor #'+key),values:labels.map(label=>({label,value:0}))});const group=groups.get(key);labels.forEach((label,index)=>{group.values[index].value+=Number(valueOf(row,label))||0})}const result=[...groups.values()].sort((a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true}));const counts=new Map();result.forEach(item=>counts.set(item.label,(counts.get(item.label)||0)+1));result.forEach(item=>{if(counts.get(item.label)>1)item.label+=' · #'+item.id});return result}
 function multiLine(spec){
  const unit=spec.options.unit||'money',series=spec.options.lineSeries.map(item=>({id:String(item.id??'none'),label:String(item.label??'Sem setor'),values:item.values.map(point=>({label:String(point.label),value:point.value==null||!Number.isFinite(Number(point.value))?null:Number(point.value)}))}));
  const labels=[...new Set(series.flatMap(item=>item.values.map(point=>point.label)))],values=series.flatMap(item=>item.values.map(point=>point.value)).filter(value=>value!=null&&Number.isFinite(value));
  const min=Math.min(0,...values),max=Math.max(0,...values)||(min<0?0:1),span=max-min||1,step=Math.max(44,Math.min(92,(spec.options.lineWidth||Math.min(560,Math.max(240,(globalThis.innerWidth||640)-80)))/Math.max(1,labels.length))),height=180;
  const matrix=series.map(item=>({...item,points:new Map(item.values.map(point=>[point.label,point.value]))}));
  const layers=matrix.map(item=>{const color=sectorColor(item.id),points=labels.map((label,index)=>{const value=item.points.get(label);return value==null||!Number.isFinite(value)?null:{x:index*step+step/2,y:(max-value)/span*height,label,value}});return `<span class="gc-series-layer" data-line-series="${escape(item.id)}" style="--series-color:${color}">${points.map((point,index)=>{if(!point)return '';const next=points[index+1],dx=next?next.x-point.x:0,dy=next?next.y-point.y:0;return `${next?`<i class="gc-segment" style="left:${point.x}px;top:${point.y}px;width:${Math.hypot(dx,dy)}px;transform:rotate(${Math.atan2(dy,dx)}rad)"></i>`:''}<b class="gc-point" title="${escape(item.label)} · ${escape(point.label)}: ${escape(format(point.value,unit))}" style="left:${point.x}px;top:${point.y}px"></b>`}).join('')}</span>`}).join('');
  const legend=`<ul class="gc-series-legend" aria-label="Legenda dos setores">${matrix.map(item=>`<li data-series-legend="${escape(item.id)}"><i style="background:${sectorColor(item.id)}"></i>${escape(item.label)}</li>`).join('')}</ul>`;
  const table=`<div class="tw"><table><thead><tr><th>Setor</th>${labels.map(label=>`<th>${escape(label)}</th>`).join('')}</tr></thead><tbody>${matrix.map(item=>`<tr><th scope="row">${escape(item.label)}</th>${labels.map(label=>{const value=item.points.get(label);return `<td>${value==null||!Number.isFinite(value)?'Indisponível':format(value,unit)}</td>`}).join('')}</tr>`).join('')}</tbody></table></div>`;
  const description=matrix.map(item=>item.label+': '+labels.map(label=>label+' '+(item.points.get(label)==null?'indisponível':format(item.points.get(label),unit))).join('; ')).join('. ');
  return `<div class="gc-visual" role="group" aria-label="${escape(spec.options.title||'Linhas por setor')}. ${escape(description)}" data-chart-rendered="line" data-sector-lines><div class="gc-scroll"><div class="gc-line gc-multi-line" style="width:${Math.max(step*labels.length,step*2)}px"><i class="gc-zero" style="top:${max/span*100}%"></i>${layers}${labels.map((label,index)=>`<span class="gc-line-label" style="left:${index*step+step/2}px">${escape(label)}</span>`).join('')}</div></div>${legend}<details><summary>Ver valores por setor</summary>${table}</details></div>`;
 }
 function content(spec,type){
  const {rows,options,original}=spec,unit=options.unit||'money';
  if(type==='original')return original;
  if(type==='line'&&options.lineSeries?.length)return multiLine(spec);
  if(!rows.length)return '<p class="sub">Sem dados neste período.</p>';
  const text=rows.map(row=>row.label+': '+format(row.value,unit)).join('; '),aria=escape((options.title||'Gráfico')+'. '+text);
  const table=`<div class="tw"><table><thead><tr><th>Categoria / período</th><th>Valor</th></tr></thead><tbody>${rows.map(row=>`<tr><th scope="row">${escape(row.label)}</th><td>${format(row.value,unit)}</td></tr>`).join('')}</tbody></table></div>`;
  if(type==='table')return table;
  const values=rows.map(row=>row.value),min=Math.min(0,...values),max=Math.max(0,...values)||(min<0?0:1),span=max-min||1,abs=Math.max(1,...values.map(Math.abs));
  let plot='';
  if(type==='bars')plot=`<div class="gc-bars">${rows.map(row=>{const width=Math.abs(row.value)/abs*(min<0?50:100),left=min<0?(row.value<0?50-width:50):0;return `<div class="gc-row"><span>${escape(row.label)}</span><span class="gc-track">${min<0?'<i class="gc-axis"></i>':''}<b style="left:${left}%;width:${width}%;background:var(--${row.value<0?'r':row.color})"></b></span><strong>${format(row.value,unit)}</strong></div>`}).join('')}</div>`;
  if(type==='columns')plot=`<div class="gc-scroll"><div class="gc-columns">${rows.map(row=>`<div class="gc-column"><div class="gc-column-plot"><i class="gc-zero" style="top:${max/span*100}%"></i><b style="top:${(max-Math.max(0,row.value))/span*100}%;height:${Math.abs(row.value)/span*100}%;background:var(--${row.value<0?'r':row.color})"></b></div><strong>${format(row.value,unit)}</strong><span>${escape(row.label)}</span></div>`).join('')}</div></div>`;
  if(type==='donut'){
   const total=values.reduce((sum,value)=>sum+value,0);let offset=0;
   const stops=rows.filter(row=>row.value>0).map(row=>{const start=offset;offset+=row.value/total*100;return `var(--${row.color}) ${start}% ${offset}%`});
   plot=`<div class="gc-donut-layout"><div class="gc-donut" style="background:${total?'conic-gradient('+stops.join(',')+')':'var(--hair)'}"><span>${total?format(total,unit):'Sem valores positivos'}</span></div>${options.externalLegend?'':`<ul class="gc-legend">${rows.map(row=>`<li><i style="background:var(--${row.color})"></i><span>${escape(row.label)}</span><strong>${format(row.value,unit)}</strong></li>`).join('')}</ul>`}</div>`;
  }
  if(type==='line'){
   const step=76,height=180,points=rows.map((row,index)=>({x:index*step+step/2,y:(max-row.value)/span*height,row}));
   plot=`<div class="gc-scroll"><div class="gc-line" style="width:${Math.max(step*rows.length,step*2)}px"><i class="gc-zero" style="top:${max/span*100}%"></i>${points.map((point,index)=>{const next=points[index+1],dx=next?next.x-point.x:0,dy=next?next.y-point.y:0;return `${next?`<i class="gc-segment" style="left:${point.x}px;top:${point.y}px;width:${Math.hypot(dx,dy)}px;transform:rotate(${Math.atan2(dy,dx)}rad)"></i>`:''}<b class="gc-point" title="${escape(point.row.label)}: ${escape(format(point.row.value,unit))}" style="left:${point.x}px;top:${point.y}px"></b><span class="gc-line-label" style="left:${point.x}px">${escape(point.row.label)}</span>`}).join('')}</div></div><details><summary>Ver valores</summary>${table}</details>`;
  }
  return `<div class="gc-visual" role="group" aria-label="${aria}" data-chart-rendered="${type}">${plot}</div>`;
 }
 function fitSectorLine(host){if(host.dataset.chartType!=='line')return;const spec=JSON.parse(host.dataset.chartSpec);if(!spec.options.lineSeries?.length)return;spec.options.lineWidth=host.clientWidth||Math.min(560,Math.max(240,(globalThis.innerWidth||640)-80));host.querySelector('[data-chart-output]').innerHTML=content(spec,'line');const scroll=host.querySelector('.gc-scroll'),labels=spec.options.lineSeries.flatMap(item=>item.values.map(point=>point.label));if(scroll&&labels.every(label=>/^\d{2}\/\d{4}$/.test(label)))scroll.scrollLeft=scroll.scrollWidth-scroll.clientWidth}
 function view(key,source,original,options={}){
  const rows=normalize(source),available=types(rows,options),type=available.some(([id])=>id===preferences[key])?preferences[key]:'original';
  const spec={key,rows,original,options};
  if(type==='line'&&options.lineSeries?.length&&typeof document!=='undefined')setTimeout(()=>{for(const host of document.querySelectorAll('[data-chart-key]'))if(host.dataset.chartKey===key)fitSectorLine(host)},0);
  return `<div class="graph-switch" data-chart-key="${escape(key)}" data-chart-spec="${escape(JSON.stringify(spec))}" data-chart-type="${type}"><label class="gc-picker">Tipo de gráfico<select aria-label="Tipo de gráfico · ${escape(options.title||key)}" onchange="SIGICharts.change(this)">${available.map(([id,label])=>`<option value="${id}" ${id===type?'selected':''}>${label}</option>`).join('')}</select></label><div data-chart-output>${content(spec,type)}</div></div>`;
 }
 function change(select){const host=select.closest('[data-chart-spec]'),spec=JSON.parse(host.dataset.chartSpec),available=types(spec.rows,spec.options);if(!available.some(([id])=>id===select.value))return;preferences[spec.key]=select.value;try{sessionStorage.setItem(storageKey,JSON.stringify(preferences))}catch{}host.dataset.chartType=select.value;host.querySelector('[data-chart-output]').innerHTML=content(spec,select.value);if(spec.options.lineSeries?.length)fitSectorLine(host)}
 globalThis.SIGICharts={view,change,types,content,sectorColor,sectorLines};
})();
