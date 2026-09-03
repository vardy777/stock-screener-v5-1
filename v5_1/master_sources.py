"""Official exchange master adapters and Eastmoney cross verification.

Live modes always perform real HTTP requests.  The injectable transport exists
only so TEST/REPLAY can exercise parsing and failure contracts without network
or production facts.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from collections import Counter,defaultdict
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
    def _runtime_error(self,code,exc):
        diagnostic={"source":self.exchange,"stage":"OFFICIAL_SOURCE_REQUEST","endpoint":self.endpoint,"error_code":code,"underlying_exception_type":type(exc).__name__,"underlying_exception_message":str(exc)}
        error=RuntimeError(f"{self.exchange} {code}: {type(exc).__name__}: {exc}");error.diagnostic=diagnostic;return error
    def _request(self,url,*,binary=False):
        if self.transport:
            try:return self.transport(url)
            except OSError as exc:raise self._runtime_error("OFFICIAL_SOURCE_UNAVAILABLE",exc) from exc
        request=Request(url,headers={"Referer":self.endpoint,"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"})
        last=None
        for attempt in range(self.retries):
            try:
                with urlopen(request,timeout=self.timeout) as response:
                    body=response.read()
                    return response.status,body if binary else body.decode("utf-8-sig","replace")
            except OSError as exc:last=exc
            if attempt+1<self.retries:time.sleep(.25)
        raise self._runtime_error("OFFICIAL_SOURCE_UNAVAILABLE",last) from last
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
    @staticmethod
    def _row_id(row):return f"sse-row:{str(row.get('NUM') or 'UNKNOWN').strip()}"
    @staticmethod
    def _delisted(row,retrieved):
        raw=str(row.get("DELIST_DATE") or "").strip().replace("/","-").replace(".","-")
        if not raw or raw=="-":return False
        if len(raw)==8 and raw.isdigit():raw=f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        try:return datetime.fromisoformat(raw).date()<=datetime.fromisoformat(retrieved).date()
        except ValueError as exc:raise ValueError("invalid SSE DELIST_DATE") from exc
    @staticmethod
    def _company_signature(row):
        return tuple(str(row.get(key) or "").strip() for key in ("A_STOCK_CODE","B_STOCK_CODE","COMPANY_CODE","COMPANY_ABBR","FULL_NAME","LIST_BOARD","DELIST_DATE","STATE_CODE","STATE_CODE_STOCK","PRODUCT_STATUS"))
    @staticmethod
    def _identity_signature(row):
        return tuple(str(row.get(key) or "").strip() for key in ("A_STOCK_CODE","COMPANY_CODE","COMPANY_ABBR","FULL_NAME","SEC_NAME_FULL","LISTING_DATE","LIST_DATE","DELIST_DATE","STATE_CODE","STATE_CODE_STOCK","STOCK_TYPE","LIST_BOARD","PRODUCT_STATUS"))
    def _failure(self,code,*,http_status,raw_sha256,raw_count,parsed_count,canonical_count,duplicate_count,classifications,conflicts,underlying="",underlying_type="ContractViolation",unique_count=None):
        diagnostic={"source":"SSE","stage":"SSE_SECURITY_MASTER_CANONICALIZATION","endpoint":self.endpoint,"http_status":http_status,"raw_response_sha256":raw_sha256,"raw_record_count":raw_count,"parsed_record_count":parsed_count,"canonical_record_count":canonical_count,"unique_symbol_count":canonical_count if unique_count is None else unique_count,"duplicate_group_count":duplicate_count,"classification_counts":dict(sorted(Counter(classifications).items())),"conflicting_symbols_sample":sorted(conflicts)[:20],"error_code":code,"underlying_exception_type":underlying_type,"underlying_exception_message":underlying or code}
        error=ContractViolation(json.dumps(diagnostic,sort_keys=True,separators=(",",":")));error.diagnostic=diagnostic;return error
    def _canonical_record(self,row,retrieved,source_record_id):
        record=self._record(row.get("A_STOCK_CODE"),row.get("COMPANY_ABBR") or row.get("SECURITY_ABBR_A"),row.get("LISTING_DATE") or row.get("LIST_DATE"),retrieved)
        if record is None:return None
        return {**record,"source_record_id":source_record_id,"master_status":"ACTIVE"}
    def discover(self):
        started=time.monotonic();retrieved=datetime.now(CHINA_TZ).isoformat();params={"sqlId":"COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L","isPagination":"true","pageHelp.pageSize":"5000","pageHelp.pageNo":"1","pageHelp.beginPage":"1","pageHelp.endPage":"1"};status,raw=self._get(self.endpoint+"?"+urlencode(params))
        if status!=200:
            exc=RuntimeError(f"HTTP {status}");error=self._runtime_error("OFFICIAL_SOURCE_HTTP_FAILURE",exc);error.diagnostic["http_status"]=status;raise error
        raw_bytes=raw.encode("utf-8") if isinstance(raw,str) else raw;raw_sha=hashlib.sha256(raw_bytes).hexdigest()
        try:payload=self._json(raw)
        except Exception as exc:raise self._failure("OFFICIAL_SOURCE_PARSE_FAILURE",http_status=status,raw_sha256=raw_sha,raw_count=0,parsed_count=0,canonical_count=0,duplicate_count=0,classifications=(),conflicts=(),underlying=str(exc),underlying_type=type(exc).__name__) from exc
        rows=payload.get("result") or payload.get("data") or [];parsed=[];missing=[]
        for row in rows:
            raw_symbol=row.get("A_STOCK_CODE") or row.get("SECURITY_CODE_A")
            record=self._record(raw_symbol,row.get("COMPANY_ABBR") or row.get("SECURITY_ABBR_A"),row.get("LISTING_DATE") or row.get("LIST_DATE"),retrieved)
            if record:parsed.append(row)
            else:missing.append({"symbol":str(raw_symbol or "UNKNOWN"),"reason":"MISSING_OR_INVALID_IDENTITY_METADATA"})
        grouped=defaultdict(list)
        for row in parsed:grouped[str(row.get("A_STOCK_CODE") or row.get("SECURITY_CODE_A")).strip().zfill(6)].append(row)
        canonical=[];duplicate_facts=[];classifications=[];historical=0;excluded=0;conflicts=[]
        duplicate_count=sum(len(group)>1 for group in grouped.values())
        for symbol,group in sorted(grouped.items()):
            ordered=sorted(group,key=lambda item:(self._identity_signature(item),self._row_id(item)))
            try:current=[row for row in ordered if not self._delisted(row,retrieved)]
            except ValueError as exc:raise self._failure("SSE_CANONICALIZATION_FAILURE",http_status=status,raw_sha256=raw_sha,raw_count=len(rows),parsed_count=len(parsed),canonical_count=len(canonical),duplicate_count=duplicate_count,classifications=classifications,conflicts=[symbol],underlying=str(exc),underlying_type=type(exc).__name__,unique_count=len(grouped)) from exc
            historical+=len(ordered)-len(current);excluded+=len(ordered)-len(current)
            if len(ordered)>1:
                identities={self._identity_signature(row) for row in ordered};types=sorted(str(row.get("STOCK_TYPE") or "").strip() for row in ordered);same_company=len({self._company_signature(row) for row in ordered})==1
                if len(current)==1 and len(ordered)>len(current):selected=current[0];kind="CURRENT_PLUS_DELISTED"
                elif len(identities)==1:selected=ordered[0];kind="EXACT_DUPLICATE_SOURCE_ROW"
                elif len(ordered)==2 and types==["1","2"] and same_company and str(ordered[0].get("B_STOCK_CODE") or "").strip().startswith("9"):
                    selected=next(row for row in ordered if str(row.get("STOCK_TYPE") or "").strip()=="1");kind="CATEGORY_VARIANT"
                else:
                    current_a=[row for row in current if str(row.get("STOCK_TYPE") or "").strip()=="1"]
                    kind="GENUINE_CURRENT_IDENTITY_CONFLICT" if len(current_a)>1 else "UNKNOWN";classifications.append(kind);conflicts.append(symbol);code="AMBIGUOUS_CURRENT_IDENTITY" if kind=="GENUINE_CURRENT_IDENTITY_CONFLICT" else "DUPLICATE_SECURITY_IDENTITY"
                    raise self._failure(code,http_status=status,raw_sha256=raw_sha,raw_count=len(rows),parsed_count=len(parsed),canonical_count=len(canonical),duplicate_count=duplicate_count,classifications=classifications,conflicts=conflicts,unique_count=len(grouped))
                canonicalized=selected in current;classifications.append(kind)
                if canonicalized:excluded+=len(current)-1
                decisions={"CURRENT_PLUS_DELISTED":"SELECT_SOLE_CURRENT_RECORD","EXACT_DUPLICATE_SOURCE_ROW":"COLLAPSE_EXACT_DUPLICATE","CATEGORY_VARIANT":"SELECT_A_SHARE_CATEGORY"}
                decision=decisions[kind] if canonicalized else "EXCLUDE_DELISTED_CATEGORY_GROUP"
                duplicate_facts.append({"symbol":symbol,"classification":kind,"source_record_ids":sorted(self._row_id(row) for row in ordered),"selected_source_record_id":self._row_id(selected),"excluded_source_record_ids":sorted(self._row_id(row) for row in ordered if row is not selected),"canonicalized":canonicalized,"decision":decision})
                if not canonicalized:continue
            else:
                if not current:continue
                selected=current[0]
            source_id=f"sse:a-share:{symbol}"
            record=self._canonical_record(selected,retrieved,source_id)
            if record is None:raise self._failure("SSE_CANONICALIZATION_FAILURE",http_status=status,raw_sha256=raw_sha,raw_count=len(rows),parsed_count=len(parsed),canonical_count=len(canonical),duplicate_count=duplicate_count,classifications=classifications,conflicts=[symbol],unique_count=len(grouped))
            canonical.append(record)
        if not canonical:raise self._failure("OFFICIAL_SOURCE_EMPTY",http_status=status,raw_sha256=raw_sha,raw_count=len(rows),parsed_count=len(parsed),canonical_count=0,duplicate_count=duplicate_count,classifications=classifications,conflicts=(),underlying="sse official directory has no valid identity records",unique_count=len(grouped))
        canonical=tuple(sorted(canonical,key=lambda item:item["code"]));codes=[item["code"] for item in canonical]
        if len(codes)!=len(set(codes)):raise self._failure("DUPLICATE_SECURITY_IDENTITY",http_status=status,raw_sha256=raw_sha,raw_count=len(rows),parsed_count=len(parsed),canonical_count=len(canonical),duplicate_count=duplicate_count,classifications=classifications,conflicts=[code for code,count in Counter(codes).items() if count>1],unique_count=len(grouped))
        diagnostic={"provider_family":"sse","exchange":"SSE","endpoint":self.endpoint,"retrieved_at":retrieved,"raw_sha256":raw_sha,"raw_content_b64":base64.b64encode(raw_bytes).decode("ascii"),"http_status":status,"records":len(rows),"valid_records":len(canonical),"raw_record_count":len(rows),"parsed_record_count":len(parsed),"canonical_record_count":len(canonical),"unique_symbol_count":len(grouped),"duplicate_group_count":duplicate_count,"classification_counts":dict(sorted(Counter(classifications).items())),"duplicate_classifications":duplicate_facts,"unexplained_duplicate_groups":0,"historical_or_delisted_record_count":historical,"excluded_record_count":excluded,"invalid_record_count":len(missing),"missing_identity_metadata":missing,"elapsed_seconds":round(time.monotonic()-started,3),"official_independent_source":True}
        return canonical,diagnostic

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
        if not official:raise ContractViolation("OFFICIAL_SOURCE_EMPTY: official master merge empty")
        if len(codes)!=len(set(codes)):raise ContractViolation("OFFICIAL_MERGE_DUPLICATE_SECURITY_IDENTITY")
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
