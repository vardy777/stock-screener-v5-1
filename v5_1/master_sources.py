"""Official exchange master adapters and Eastmoney cross verification.

Live modes always perform real HTTP requests.  The injectable transport exists
only so TEST/REPLAY can exercise parsing and failure contracts without network
or production facts.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import base64,hashlib,json,re,time,unicodedata
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from xml.etree import ElementTree
from zipfile import ZipFile
from shared_core.core import CHINA_TZ
from .providers import EastmoneyMasterDirectory
from shared_core.core import ContractViolation
from .security_master import SecurityMasterVersionV1,reconcile_provider_records

@dataclass(frozen=True)
class DirectoryProvider:
    source_id:str;provider_family:str;exchange:str;independent:bool;live_status:str="PENDING_LIVE_ACCEPTANCE"
    def parse(self,rows,known_at):
        values=[]
        for raw in rows:
            symbol=str(raw.get("symbol","")).zfill(6)
            exchange=str(raw.get("exchange",self.exchange))
            if exchange!=self.exchange:raise ContractViolation("official directory exchange mismatch")
            values.append(SecurityMasterVersionV1.build(symbol=symbol,exchange=exchange,board=str(raw["board"]),security_name=raw["security_name"],listing_date=raw["listing_date"],delisting_date=raw.get("delisting_date"),master_status=raw.get("master_status","ACTIVE"),is_a_share=raw.get("is_a_share",True),valid_from=raw.get("valid_from",raw["listing_date"]),valid_to=raw.get("valid_to"),known_at=known_at,source_family=self.provider_family,source_record_id=str(raw.get("source_record_id",symbol))))
        if not values:raise ContractViolation("official directory empty")
        return tuple(values)

SSE_OFFICIAL=DirectoryProvider("sse_official_security_list","sse","SSE",True)
SZSE_OFFICIAL=DirectoryProvider("szse_official_security_list","szse","SZSE",True)
EASTMONEY_DIRECTORY=DirectoryProvider("eastmoney_market_directory","eastmoney","SSE",False)

def build_independent_master(source_rows,known_at):
    parsed={provider.provider_family:provider.parse(rows,known_at) for provider,rows in source_rows}
    independent=[provider.provider_family for provider,_ in source_rows if provider.independent]
    return reconcile_provider_records(parsed,independent)

def normalize_security_name(value):
    value=unicodedata.normalize("NFKC",str(value or ""));value="".join(value.split())
    return re.sub(r"^(?:\*ST|ST)","",value,flags=re.I)

class OfficialMasterSource:
    provider_family="";exchange="";endpoint="";source_id="";retries=2;timeout=8
    def __init__(self,transport=None):self.transport=transport
    def _request(self,url,*,binary=False):
        if self.transport:return self.transport(url)
        request=Request(url,headers={"Referer":self.endpoint,"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"})
        last=None
        for attempt in range(self.retries):
            try:
                with urlopen(request,timeout=self.timeout) as response:
                    body=response.read()
                    return response.status,body if binary else body.decode("utf-8-sig","replace")
            except OSError as exc:last=exc
            if attempt+1<self.retries:time.sleep(.25)
        raise RuntimeError(f"{self.provider_family} official source unavailable: {type(last).__name__}") from last
    def _get(self,url):return self._request(url)
    def _record(self,symbol,name,listing_date,retrieved_at):
        symbol=str(symbol or "").strip().zfill(6);name=str(name or "").strip();raw=str(listing_date or "").strip().replace("/","-").replace(".","-")
        if len(raw)==8 and raw.isdigit():raw=f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        try:datetime.fromisoformat(raw)
        except ValueError:return None
        if len(symbol)!=6 or not symbol.isdigit() or not name:return None
        valid_exchange=(self.exchange=="SSE" and symbol.startswith("6")) or (self.exchange=="SZSE" and symbol.startswith(("00","30")))
        if not valid_exchange:return None
        return {"code":symbol,"exchange":self.exchange,"name":name,"listing_date":raw,"source_family":self.provider_family,"source_url":self.endpoint,"source_record_id":f"{self.provider_family}:{symbol}","retrieved_at":retrieved_at}

    @staticmethod
    def _json(raw):
        start=raw.find("{");end=raw.rfind("}")
        if start<0 or end<start:raise ContractViolation("official directory response is not JSON")
        return json.loads(raw[start:end+1])

class SSEOfficialMasterSource(OfficialMasterSource):
    provider_family="sse";exchange="SSE";source_id="sse_official_share_list";endpoint="https://query.sse.com.cn/sseQuery/commonQuery.do"
    def discover(self):
        started=time.monotonic();retrieved=datetime.now(CHINA_TZ).isoformat();params={"sqlId":"COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L","isPagination":"true","pageHelp.pageSize":"5000","pageHelp.pageNo":"1","pageHelp.beginPage":"1","pageHelp.endPage":"1"};status,raw=self._get(self.endpoint+"?"+urlencode(params))
        if status!=200:raise RuntimeError(f"sse official HTTP {status}")
        payload=self._json(raw);rows=payload.get("result") or payload.get("data") or [];valid=[];missing=[]
        for row in rows:
            raw_symbol=row.get("A_STOCK_CODE") or row.get("SECURITY_CODE_A") or row.get("COMPANY_CODE")
            record=self._record(raw_symbol,row.get("COMPANY_ABBR") or row.get("SECURITY_ABBR_A"),row.get("LISTING_DATE") or row.get("LIST_DATE"),retrieved)
            if record:valid.append(record)
            else:missing.append({"symbol":str(raw_symbol or "UNKNOWN"),"reason":"MISSING_OR_INVALID_IDENTITY_METADATA"})
        if not valid:raise ContractViolation("sse official directory has no valid identity records")
        raw_bytes=raw.encode("utf-8") if isinstance(raw,str) else raw
        return tuple(valid),{"provider_family":"sse","exchange":"SSE","endpoint":self.endpoint,"retrieved_at":retrieved,"raw_sha256":hashlib.sha256(raw_bytes).hexdigest(),"raw_content_b64":base64.b64encode(raw_bytes).decode("ascii"),"http_status":status,"records":len(rows),"valid_records":len(valid),"missing_identity_metadata":missing,"elapsed_seconds":round(time.monotonic()-started,3),"official_independent_source":True}

class SZSEOfficialMasterSource(OfficialMasterSource):
    provider_family="szse";exchange="SZSE";source_id="szse_official_company_list";endpoint="https://www.szse.cn/api/report/ShowReport"
    @staticmethod
    def _xlsx_rows(raw):
        ns={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"};rows=[]
        with ZipFile(BytesIO(raw)) as archive:
            root=ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            for row in root.findall(".//m:sheetData/m:row",ns):
                values={}
                for cell in row.findall("m:c",ns):
                    ref=str(cell.get("r",""));column=re.sub(r"\d+$","",ref);value="".join(node.text or "" for node in cell.findall(".//m:t",ns))
                    if not value:
                        node=cell.find("m:v",ns);value=node.text or "" if node is not None else ""
                    values[column]=value
                if str(values.get("E","")).strip().isdigit():rows.append({"agdm":values.get("E"),"agjc":values.get("F"),"agssrq":values.get("G")})
        return rows
    def discover(self):
        started=time.monotonic();retrieved=datetime.now(CHINA_TZ).isoformat();url=self.endpoint+"?"+urlencode({"SHOWTYPE":"xlsx","CATALOGID":"1110","TABKEY":"tab1","random":f"{time.time():.6f}"});status,raw=self._request(url,binary=True)
        if status!=200:raise RuntimeError(f"szse official HTTP {status}")
        if isinstance(raw,str):
            payload=json.loads(raw);containers=payload if isinstance(payload,list) else payload.get("data") or payload.get("result") or [];rows=[]
            for item in containers:rows.extend(item.get("data",[]) if isinstance(item,dict) and isinstance(item.get("data"),list) else [item])
        else:rows=self._xlsx_rows(raw)
        valid=[];missing=[]
        for row in rows:
            code=row.get("agdm") or row.get("zqdm") or row.get("证券代码") or row.get("code");record=self._record(code,row.get("agjc") or row.get("zqjc") or row.get("证券简称") or row.get("name"),row.get("agssrq") or row.get("ssrq") or row.get("上市日期") or row.get("listing_date"),retrieved)
            if record:valid.append(record)
            else:missing.append({"symbol":str(code or "UNKNOWN"),"reason":"MISSING_OR_INVALID_IDENTITY_METADATA"})
        if not valid:raise ContractViolation("szse official directory has no valid identity records")
        raw_bytes=raw.encode("utf-8") if isinstance(raw,str) else raw
        return tuple(valid),{"provider_family":"szse","exchange":"SZSE","endpoint":self.endpoint,"retrieved_at":retrieved,"raw_sha256":hashlib.sha256(raw_bytes).hexdigest(),"raw_content_b64":base64.b64encode(raw_bytes).decode("ascii"),"http_status":status,"records":len(rows),"valid_records":len(valid),"missing_identity_metadata":missing,"elapsed_seconds":round(time.monotonic()-started,3),"official_independent_source":True}

class CrossVerifiedMasterDirectory:
    """Official exchange base master with optional Eastmoney cross-check.

    SSE/SZSE are authoritative for their own markets.  Eastmoney is never a
    discovery prerequisite and an outage degrades third-party verification
    without discarding a complete, internally valid official base.
    """
    provider_family="eastmoney";source_id="eastmoney_plus_official_exchange"
    def __init__(self,eastmoney=None,sse=None,szse=None):self.eastmoney=eastmoney or EastmoneyMasterDirectory();self.sse=sse or SSEOfficialMasterSource();self.szse=szse or SZSEOfficialMasterSource()
    def discover(self):
        sse_rows,sse_diag=self.sse.discover();szse_rows,szse_diag=self.szse.discover()
        official=tuple(sorted((*sse_rows,*szse_rows),key=lambda x:x["code"]));codes=[x["code"] for x in official]
        if not official or len(codes)!=len(set(codes)):raise ContractViolation("official master empty or duplicate symbol")
        east_error=None
        try:discovered,east_diag=self.eastmoney.discover()
        except Exception as exc:
            discovered=();east_error=f"{type(exc).__name__}: {exc}";east_diag={"provider_family":"eastmoney","status":"UNAVAILABLE","error":east_error}
        discovered_by_code={str(x["code"]).zfill(6):x for x in discovered}
        if len(discovered_by_code)!=len(discovered):raise ContractViolation("Eastmoney directory duplicate symbol")
        retrieved=datetime.now(CHINA_TZ).isoformat();east_raw=json.dumps(discovered,ensure_ascii=False,sort_keys=True,separators=(",",":"));east_bytes=east_raw.encode()
        east_responses=[]
        for item in east_diag.get("raw_responses",()):east_responses.append({"provider_family":"eastmoney","exchange":"ALL",**item})
        if not east_error and not east_responses:east_responses=[{"provider_family":"eastmoney","exchange":"ALL","endpoint":str(east_diag.get("endpoint") or "injected://eastmoney-directory"),"retrieved_at":retrieved,"raw_sha256":hashlib.sha256(east_bytes).hexdigest(),"raw_content_b64":base64.b64encode(east_bytes).decode("ascii"),"record_count":len(discovered),"response_key":"eastmoney-injected-normalized"}]
        responses=[{k:d[k] for k in ("provider_family","exchange","endpoint","retrieved_at","raw_sha256","raw_content_b64")}|{"record_count":d["valid_records"]} for d in (sse_diag,szse_diag)]
        if not east_error:responses.extend(east_responses)
        matches=[];conflicts=[];matched=0;missing=0
        for row in official:
            third=discovered_by_code.get(row["code"]);outcome="THIRD_PARTY_UNAVAILABLE" if east_error else "THIRD_PARTY_MISSING" if third is None else "MATCH"
            if third is not None and (normalize_security_name(row["name"])!=normalize_security_name(third.get("name")) or row["listing_date"]!=third.get("listing_date")):
                outcome="CONFLICT";conflicts.append({"symbol":row["code"],"reason":"IDENTITY_CONFLICT"})
            matched+=outcome=="MATCH";missing+=outcome in {"THIRD_PARTY_MISSING","THIRD_PARTY_UNAVAILABLE"}
            matches.append({"symbol":row["code"],"exchange":row["exchange"],"official_family":row["source_family"],"third_party_family":"eastmoney" if not east_error else None,"third_party_response_key":third.get("source_response_key") if third else None,"official_name":row["name"],"official_listing_date":row["listing_date"],"third_party_name":third.get("name") if third else None,"third_party_listing_date":third.get("listing_date") if third else None,"outcome":outcome,"matched_at":retrieved})
        if conflicts:raise ContractViolation(f"official/third-party identity conflicts={len(conflicts)}")
        diag={"provider_family":"official_exchange_master","source_families":["sse","szse"]+([] if east_error else ["eastmoney"]),"independent_source_families":["sse","szse"],"official_independent_source":True,"verification_status":"DEGRADED_THIRD_PARTY_UNAVAILABLE" if east_error else "VERIFIED" if not missing else "DEGRADED_THIRD_PARTY_PARTIAL","responses":responses,"matches":matches,"eastmoney":east_diag,"sse":{**sse_diag,"verified":sum(x["exchange"]=="SSE" and x["outcome"]=="MATCH" for x in matches)},"szse":{**szse_diag,"verified":sum(x["exchange"]=="SZSE" and x["outcome"]=="MATCH" for x in matches)},"matched":matched,"third_party_missing":missing,"conflicts":conflicts,"bse":{"status":"EXCLUDED_BY_CONTRACT","symbols":sorted(x for x in discovered_by_code if x.startswith(("4","8")))}}
        return official,diag
