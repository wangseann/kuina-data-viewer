"""Build the public market/sector search log. Documentation is not eligibility."""
import argparse
import base64
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlparse

MARKETS = dict(forex='Forex', futures='Futures', stocks='Stocks / ETFs', crypto='Crypto',
               commodities='Commodities / power', indices='Indices', options='Options')
STATUSES = dict(metadata_needed='Instrument metadata needed', access_required='Free account / access check',
                known_incomplete='Known coverage issue', rejected='Does not meet requirements')
ACCESS = dict(public_archive='Free · no login', free_login='Free · login required')
FIELDS = {'id','market','sector','region','provider','resolution','history','access','status','next_step','source_url'}
HOSTS = {
    'www.truefx.com', 'github.com', 'www.histdata.com', 'docs.alpaca.markets',
    'upstox.com', 'support.kraken.com', 'public.bybit.com', 'www.okx.com',
    'docs.cdp.coinbase.com', 'docs.bitfinex.com', 'www.bitstamp.net',
    'www.cryptodatadownload.com', 'statics.deribit.com', 'www.aemo.com.au',
    'www.ercot.com',
}


def validate(data):
    if not isinstance(data,dict) or set(data) != {'schema','checked_at','window_start','window_end_exclusive','sources'}:
        raise ValueError('Closed public source-search metadata required')
    if data['schema'] != 'kuina-acquisition-search-v1' or (data['window_start'],data['window_end_exclusive']) != ('2024-10-01','2026-10-01'):
        raise ValueError('Unreviewed source-search schema or window')
    if not isinstance(data['checked_at'],str) or not data['checked_at'].endswith('Z'):
        raise ValueError('UTC review date required')
    datetime.fromisoformat(data['checked_at'].replace('Z','+00:00'))
    if not isinstance(data['sources'],list) or not 0 < len(data['sources']) <= 100:
        raise ValueError('Bounded source-search rows required')
    seen=set()
    for row in data['sources']:
        if not isinstance(row,dict) or set(row) != FIELDS:
            raise ValueError('Unexpected source-search fields')
        if any(not isinstance(v,str) or not v or len(v)>500 for v in row.values()):
            raise ValueError('Bounded public text required')
        if not re.fullmatch('[a-z0-9-]{1,96}',row['id']) or row['id'] in seen:
            raise ValueError('Unique source-search ID required')
        seen.add(row['id'])
        if row['market'] not in MARKETS or row['status'] not in STATUSES or row['access'] not in ACCESS:
            raise ValueError('Unreviewed source-search classification')
        url=urlparse(row['source_url'])
        if url.scheme != 'https' or url.hostname not in HOSTS or url.username or url.password or url.query or url.fragment:
            raise ValueError('Official HTTPS documentation without credentials required')
        if url.hostname=='github.com' and not url.path.startswith(('/binance/binance-public-data','/fxcm/MarketData')):
            raise ValueError('Official provider repository required')
        if any('/datashare/' in v or '/Users/' in v or '/flash/' in v for v in row.values()):
            raise ValueError('Private paths do not belong in source-search metadata')
    return data


SCRIPT = """(() => {
  const market=document.getElementById('market-filter');
  const sector=document.getElementById('sector-filter');
  const status=document.getElementById('status-filter');
  const rows=[...document.querySelectorAll('tr[data-market]')];
  function filter(){
    let visible=0;
    for(const row of rows){
      row.hidden=!((market.value==='all'||row.dataset.market===market.value)&&(sector.value==='all'||row.dataset.sector===sector.value)&&(status.value==='all'||row.dataset.status===status.value));
      if(!row.hidden)visible++;
    }
    document.getElementById('visible-count').textContent=visible+' provider / sector investigations';
  }
  market.addEventListener('change',()=>{
    sector.replaceChildren(new Option('All sectors','all'));
    const values=[...new Set(rows.filter(r=>market.value==='all'||r.dataset.market===market.value).map(r=>r.dataset.sector))].sort();
    for(const value of values)sector.append(new Option(value,value));
    filter();
  });
  sector.addEventListener('change',filter);status.addEventListener('change',filter);filter();
})();"""


def render(data):
    validate(data)
    from counts import NAVIGATION
    esc=lambda value:html.escape(value,quote=True)
    def options(values):
        return ''.join('<option value="'+esc(key)+'">'+esc(label)+'</option>' for key,label in values)
    rows=[]
    for row in data['sources']:
        cells=[esc(MARKETS[row['market']]),esc(row['sector'])+'<small>'+esc(row['region'])+'</small>',
               '<a href="'+esc(row['source_url'])+'" target="_blank" rel="noopener noreferrer">'+esc(row['provider'])+'</a>',
               esc(row['resolution'])+'<small>'+esc(row['history'])+'</small>',esc(ACCESS[row['access']]),
               '<strong>'+esc(STATUSES[row['status']])+'</strong><small>'+esc(row['next_step'])+'</small>']
        rows.append('<tr data-market="'+esc(row['market'])+'" data-sector="'+esc(row['sector'])+'" data-status="'+esc(row['status'])+'">'+''.join('<td>'+v+'</td>' for v in cells)+'</tr>')
    script_hash=base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'sha256-'+script_hash+'\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>Kuina · Find new data</title><style>body{font:15px system-ui;color:#193247;background:#f5f7fa;max-width:1550px;margin:30px auto;padding:0 22px}a{color:#17658b}p{line-height:1.6}h1{font-size:32px}section{background:white;border:1px solid #dce4eb;border-radius:12px;padding:22px;margin:20px 0}.filters{display:flex;gap:18px;flex-wrap:wrap}select{font:inherit;padding:8px;margin-left:8px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:900px}th,td{padding:14px;text-align:left;border-bottom:1px solid #dce4eb;vertical-align:top}small{display:block;color:#526878;line-height:1.5;margin-top:7px}.note{color:#526878}nav{line-height:1.8}tr[hidden]{display:none}</style><body><main>'+NAVIGATION+
            '<h1>Find new data</h1><p>Search by market and sector. Prioritize broader coverage, then verify individual instruments.</p>'
            '<p class="note">Target window: October 2024–September 2026 · Native interval ≤15 minutes · Two years of actual history · Verified calendar and gaps.</p>'
            '<section><h2>Source investigations</h2><p>Free sources only: public archives or free access with registration. Markets without a verified free candidate remain uncovered.</p><p><strong>No data downloaded in this source search.</strong> Provider documentation is verified; instrument coverage and collection permission remain separate checks. No candidate below is certified eligible.</p>'
            '<div class="filters"><label>Market<select id="market-filter"><option value="all">All markets</option>'+options(MARKETS.items())+'</select></label>'
            '<label>Sector<select id="sector-filter"><option value="all">All sectors</option>'+options((v,v) for v in sorted({r['sector'] for r in data['sources']}))+'</select></label>'
            '<label>Status<select id="status-filter"><option value="all">All statuses</option>'+options(STATUSES.items())+'</select></label></div>'
            '<p id="visible-count"></p><div class="scroll"><table><thead><tr><th>Market</th><th>Sector / region</th><th>Provider</th><th>Documented data</th><th>Access</th><th>Status / Next check</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></section>'
            '<p class="note">Sector labels describe search priorities, not a verified classification of individual instruments. Quotes, trades, futures contracts and continuous series retain separate definitions.</p>'
            '<p class="note">Documentation checked '+esc(data['checked_at'][:10])+'. <a href="acquisition-sources.json">Download search log</a></p></main><script>'+SCRIPT+'</script></body></html>')


def build(data,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'sources.html').write_text(render(data))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();build(json.loads(args.input.read_text()),args.out)
