// MapLibre GL JS page for the phone map (WebView on native, iframe on Expo web). Rail-only layers; the page never fetches
// data itself: it asks the app (postMessage) so the app can cache, abort stale requests and work offline.
export const MAPLIBRE_VERSION = "5.24.0";
export const MAPLIBRE_CDN = `https://unpkg.com/maplibre-gl@${MAPLIBRE_VERSION}/dist`;

export type MapColors = { line: string; caltrans: string; path: string; station: string; pin: string; pinDone: string; text: string; halo: string; bg: string };

export function mapHtml(opts: { js?: string | null; css?: string | null; colors: MapColors; center: [number, number]; zoom: number }) {
  const lib = opts.js ? `<script>${opts.js}</script>` : `<script src="${MAPLIBRE_CDN}/maplibre-gl.js"></script>`;
  const css = opts.css ? `<style>${opts.css}</style>` : `<link rel="stylesheet" href="${MAPLIBRE_CDN}/maplibre-gl.css"/>`;
  const C = JSON.stringify(opts.colors);
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>${css}
<style>html,body,#map{margin:0;height:100%;width:100%;background:${opts.colors.bg}}
.maplibregl-popup-content{font:15px/1.35 -apple-system,Segoe UI,sans-serif;max-width:260px}.k{color:#555;font-size:12px}</style></head>
<body><div id="map"></div>${lib}<script>
(function(){
var C=${C}, post=function(m){var s=JSON.stringify(m); if(window.ReactNativeWebView){window.ReactNativeWebView.postMessage(s)} else {window.parent.postMessage(s,"*")}};
if(!window.maplibregl){post({type:"fatal",text:"Map could not load. Open RailReady once with a connection."});return;}
var EMPTY={type:"FeatureCollection",features:[]}, tiles={}, gen=0, timer=null, map=null;
var LAYERS=["ntad_lines","caltrans","ntad_mileposts","ntad_crossings","gtfs","pins","camera","draft"];
function srcData(name){var f=[],seen={};Object.keys(tiles).forEach(function(k){if(k.indexOf(name+"/")===0){(tiles[k]||[]).forEach(function(x){var id=x.properties&&x.properties._id;if(id&&seen[id])return;if(id)seen[id]=1;f.push(x)})}});return {type:"FeatureCollection",features:f}}
function refresh(name){var s=map&&map.getSource(name);if(s)s.setData(srcData(name))}
function tileXY(lon,lat,z){var n=Math.pow(2,z),x=Math.floor((lon+180)/360*n),r=lat*Math.PI/180,y=Math.floor((1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*n);return [Math.max(0,Math.min(n-1,x)),Math.max(0,Math.min(n-1,y))]}
function view(){clearTimeout(timer);timer=setTimeout(function(){gen++;var b=map.getBounds(),z=Math.min(12,Math.max(3,Math.floor(map.getZoom())));
 var a=tileXY(b.getWest(),b.getNorth(),z),c=tileXY(b.getEast(),b.getSouth(),z),list=[];
 for(var x=a[0];x<=c[0];x++)for(var y=a[1];y<=c[1];y++)list.push([z,x,y]);
 if(list.length>16)list=list.slice(0,16);
 var keep={};list.forEach(function(t){LAYERS.forEach(function(L){keep[L+"/"+t.join("/")]=1})});
 Object.keys(tiles).forEach(function(k){if(k.indexOf("gtfs/")!==0&&k.indexOf("pins/")!==0&&k.indexOf("camera/")!==0&&k.indexOf("draft/")!==0&&!keep[k])delete tiles[k]});
 post({type:"view",gen:gen,zoom:map.getZoom(),tiles:list,bbox:[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]});},300)}
function row(k,v){return v===undefined||v===null||v===""?"":'<div><span class="k">'+k+'</span> '+String(v).replace(/</g,"&lt;")+'</div>'}
function popup(e){var f=e.features&&e.features[0];if(!f)return;var p=f.properties||{};
 if(p.kind==="pin"||p.kind==="camera_first"){post({type:"open",props:p});return;}
 var h='<b>'+(p.short_name||p.name||p.RROWNER1||p.RAILROAD||p.Railroad||"Rail feature")+'</b>'+row("",p.label)+row("",p._tracks_label)+row("",p._milepost_range)+row("Milepost",p.MILEPOST)+row("Subdivision",p.SUBDIV)+row("Source",p._source)+row("Id",p._id)+row("Version",p._version)+row("Retrieved",p._retrieved_at);
 new maplibregl.Popup().setLngLat(e.lngLat).setHTML(h).addTo(map)}
function addLayers(){LAYERS.forEach(function(n){if(!map.getSource(n))map.addSource(n,{type:"geojson",data:srcData(n)})});
 map.addLayer({id:"ntad_lines",type:"line",source:"ntad_lines",paint:{"line-color":C.line,"line-width":["interpolate",["linear"],["zoom"],4,0.6,12,2.2]}});
 map.addLayer({id:"caltrans",type:"line",source:"caltrans",paint:{"line-color":C.caltrans,"line-width":1.6,"line-dasharray":[2,1]}});
 map.addLayer({id:"gtfs_paths",type:"line",source:"gtfs",filter:["==",["get","kind"],"path"],paint:{"line-color":C.path,"line-width":2.4,"line-opacity":0.85}});
 map.addLayer({id:"gtfs_stations",type:"circle",source:"gtfs",minzoom:11,filter:["any",["==",["get","kind"],"station"],["all",["==",["get","kind"],"stop"],["!",["has","parent_id"]]]],paint:{"circle-radius":4,"circle-color":"#fff","circle-stroke-color":C.station,"circle-stroke-width":2}});
 map.addLayer({id:"milepost_points",type:"circle",source:"ntad_mileposts",minzoom:11,paint:{"circle-radius":7,"circle-color":C.caltrans,"circle-stroke-color":"#fff","circle-stroke-width":2}});
 if(map.getStyle().glyphs)map.addLayer({id:"mileposts",type:"symbol",source:"ntad_mileposts",minzoom:11,layout:{"text-field":["concat","MP ",["to-string",["get","MILEPOST"]]],"text-size":11,"text-offset":[0,1.2]},paint:{"text-color":C.text,"text-halo-color":C.halo,"text-halo-width":1.5}});
 map.addLayer({id:"crossings",type:"circle",source:"ntad_crossings",minzoom:12,paint:{"circle-radius":3,"circle-color":C.caltrans}});
 map.addLayer({id:"camera",type:"circle",source:"camera",paint:{"circle-radius":6,"circle-color":"#fff","circle-stroke-color":C.text,"circle-stroke-width":2}});
 map.addLayer({id:"pins",type:"circle",source:"pins",paint:{"circle-radius":9,"circle-color":["case",["==",["get","inspection_state"],"Not inspected"],C.pin,C.pinDone],"circle-stroke-color":"#fff","circle-stroke-width":2}});
 map.addLayer({id:"draft",type:"circle",source:"draft",paint:{"circle-radius":11,"circle-color":C.caltrans,"circle-stroke-color":"#fff","circle-stroke-width":3}});
 ["caltrans","gtfs_paths","gtfs_stations","crossings"].forEach(function(l){map.on("click",l,popup)});
 map.on("click",function(e){
  var box=[[e.point.x-8,e.point.y-8],[e.point.x+8,e.point.y+8]], saved=map.queryRenderedFeatures(box,{layers:["pins","camera"]});
  if(saved.length){post({type:"open",props:saved[0].properties});return;}
  var points=map.queryRenderedFeatures(box,{layers:["milepost_points"]});
  var hits=points.length?points:map.queryRenderedFeatures(box,{layers:["ntad_lines"]}), seen={}, choices=[];
  hits.forEach(function(f){var p=f.properties||{},id=p._id;if(!id||seen[id])return;seen[id]=1;
   choices.push({id:id,label:points.length?"MP "+p.MILEPOST+" / "+(p.SUBDIV||"Subdivision unknown"):(p.RROWNER1||"Rail line")+" / "+(p.SUBDIV||"Subdivision unknown"),source:p._source});});
  if(choices.length){post({type:"rail_pick",features:choices,lat:e.lngLat.lat,lon:e.lngLat.lng});if(map.getZoom()<11)map.flyTo({center:[e.lngLat.lng,e.lngLat.lat],zoom:12});return;}
  var unreferenced=map.queryRenderedFeatures(box,{layers:["caltrans","gtfs_paths"]});
  if(unreferenced.length){post({type:"rail_unreferenced",lat:e.lngLat.lat,lon:e.lngLat.lng});return;}
  post({type:"tap",lat:e.lngLat.lat,lon:e.lngLat.lng});
 });}
function start(style){map=new maplibregl.Map({container:"map",style:style,center:${JSON.stringify(opts.center)},zoom:${opts.zoom},
 attributionControl:{compact:false,customAttribution:"Rail lines: USDOT BTS NTAD; Caltrans California Rail Network; rail-only GTFS (SFMTA, BART, Caltrain)"}});
 map.addControl(new maplibregl.NavigationControl({showCompass:true,visualizePitch:false}),"top-right");
 map.on("load",function(){addLayers();view();post({type:"loaded"})});map.on("moveend",view);
 var pressT=null;map.on("touchstart",function(e){if(e.originalEvent.touches&&e.originalEvent.touches.length>1)return;var ll=e.lngLat;pressT=setTimeout(function(){post({type:"longpress",lat:ll.lat,lon:ll.lng})},600)});
 ["touchend","touchmove","dragstart","zoomstart"].forEach(function(ev){map.on(ev,function(){clearTimeout(pressT)})});
 map.on("contextmenu",function(e){post({type:"longpress",lat:e.lngLat.lat,lon:e.lngLat.lng})});}
function onMsg(raw){var m;try{m=typeof raw==="string"?JSON.parse(raw):raw}catch(e){return}if(!m||!m.type)return;
 if(m.type==="style"){if(!map)start(m.style);else map.setStyle(m.style)}
 else if(m.type==="layer"){if(m.gen!==undefined&&m.gen<gen-1)return;tiles[m.key]=m.fc.features||[];refresh(m.key.split("/")[0])}
 else if(m.type==="fly"){map.flyTo({center:[m.lon,m.lat],zoom:m.zoom||15})}
 else if(m.type==="draft"){tiles["draft/one"]=m.lat==null?[]:[{type:"Feature",geometry:{type:"Point",coordinates:[m.lon,m.lat]},properties:{kind:"draft"}}];refresh("draft")}}
window.addEventListener("message",function(e){onMsg(e.data)});document.addEventListener("message",function(e){onMsg(e.data)});
post({type:"ready"});
})();</script></body></html>`;
}
