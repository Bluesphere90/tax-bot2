# bot/services/xml_parser.py
# Parser XML nâng cao — trích đầy đủ trường và chỉ chấp nhận ma_tb == '844'
from lxml import etree
from typing import Optional, List, Dict
import re
import unicodedata
from datetime import datetime

# namespace used in incoming XMLs (kept from original file)
NS = {"t": "http://kekhaithue.gdt.gov.vn/TBaoThue"}

def _text_or_none(elem: Optional[etree._Element]) -> Optional[str]:
    if elem is None or elem.text is None:
        return None
    return elem.text.strip()

def _strip_accents(s: str) -> str:
    nk = unicodedata.normalize("NFKD", s)
    return "".join([c for c in nk if not unicodedata.combining(c)])

def _normalize_for_match(s: Optional[str]) -> str:
    if not s:
        return ""
    s2 = s.strip().upper()
    s2 = re.sub(r"\s+", " ", s2)
    s2 = _strip_accents(s2)
    return s2

def detect_form_code_from_known(tokhai_raw: Optional[str], known_codes: List[str]) -> Optional[str]:
    """
    Try to detect canonical form_code from tokhai_raw using known_codes list.
    known_codes should be canonical strings (e.g. "01/GTGT").
    """
    if not tokhai_raw or not known_codes:
        return None
    norm_raw = _normalize_for_match(tokhai_raw)
    # build normalized map
    norm_map = { _normalize_for_match(c): c for c in known_codes }

    # 1) exact presence search (word-like)
    for norm_code, orig in norm_map.items():
        pattern = re.escape(norm_code)
        rx = re.compile(rf"(?<![A-Z0-9/]){pattern}(?![A-Z0-9/])", flags=re.IGNORECASE)
        if rx.search(norm_raw):
            return orig

    # 2) search token like dd/. in raw
    m = re.search(r"\b\d{1,3}/[A-Z0-9\-/]+\b", norm_raw)
    if m:
        token = m.group(0)
        if token in norm_map:
            return norm_map[token]
        t2 = token.rstrip("-_/")
        if t2 in norm_map:
            return norm_map[t2]

    # 3) token by token
    tokens = re.split(r"[,\s;\-()]+", norm_raw)
    for t in tokens[:12]:
        if not t:
            continue
        if t in norm_map:
            return norm_map[t]

    return None

def _safe_find(root: etree._Element, xpath: str) -> Optional[str]:
    try:
        el = root.find(xpath, namespaces=NS)
        return _text_or_none(el)
    except Exception:
        return None

def parse_submission_from_bytes(data_bytes: bytes, known_codes: Optional[List[str]] = None) -> Dict[str, Optional[str]]:
    """
    Parse XML bytes and return a dict with keys:
      - company_tax_id
      - company_name
      - address
      - ma_tb
      - so_thong_bao
      - ngay_thong_bao
      - ma_giaodich
      - tokhai_raw  (form_raw)
      - form_code   (detected canonical code if possible)
      - loai_to_khai
      - ky_thue
      - lan_nop
      - accepted (bool) -> True if ma_tb == '844' (only accept these)
    known_codes: optional list of canonical form codes to help detection
    """
    # Parse XML safely
    try:
        root = etree.fromstring(data_bytes)
    except Exception:
        # return minimal info if parse fails
        return {
            "company_tax_id": None,
            "company_name": None,
            "address": None,
            "ma_tb": None,
            "so_thong_bao": None,
            "ngay_thong_bao": None,
            "ma_giaodich": None,
            "tokhai_raw": None,
            "form_code": None,
            "loai_to_khai": None,
            "ky_thue": None,
            "lan_nop": None,
            "accepted": False,
        }

    # Basic company info
    company_tax_id = _safe_find(root, ".//t:NNhanTBaoThue/t:maNNhan")
    company_name = _safe_find(root, ".//t:NNhanTBaoThue/t:tenNNhan")
    address = _safe_find(root, ".//t:NNhanTBaoThue/t:diaChiNNhan")

    # Thong bao chung
    ma_tb = _safe_find(root, ".//t:TTinTBaoThue/t:maTBao")
    so_thong_bao = _safe_find(root, ".//t:TTinTBaoThue/t:soTBao")
    ngay_thong_bao = _safe_find(root, ".//t:TTinTBaoThue/t:ngayTBao")

    # ndung ma giao dich
    ma_giaodich = _safe_find(root, ".//t:NDungTBao/t:maGiaoDichDTu")

    # details in CTietHoSoThue / HoSoThue
    ctiet = root.find(".//t:HoSoThue//t:CTietHoSoThue", namespaces=NS)
    tokhai_raw = None
    form_code = None
    loai_to_khai = None
    ky_thue = None
    lan_nop = None

    if ctiet is not None:
        # token that often contains form info
        tk = ctiet.find("t:tokhai-phuluc", namespaces=NS)
        tokhai_raw = _text_or_none(tk)
        loai_to_khai = _text_or_none(ctiet.find("t:loaiToKhai", namespaces=NS))
        ky_thue = _text_or_none(ctiet.find("t:kyTinhThue", namespaces=NS))
        lan_nop = _text_or_none(ctiet.find("t:lanNop", namespaces=NS))
        # if there are specific tags for form code sometimes in other nodes, try more
        # e.g. node t:tenToKhai or t:maToKhai (common variants)
        if not tokhai_raw:
            tokhai_raw = _safe_find(root, ".//t:HoSoThue//t:tenToKhai") or _safe_find(root, ".//t:HoSoThue//t:maToKhai")

    # detect form_code using known_codes if provided
    if tokhai_raw and known_codes:
        detected = detect_form_code_from_known(tokhai_raw, known_codes)
        if detected:
            form_code = detected
        else:
            # fallback: take first token like '01/GTGT' or prefix before '-'
            left = tokhai_raw.split("-", 1)[0].strip()
            token = left.split()[0].strip()
            form_code = token if token else None
    else:
        if tokhai_raw:
            left = tokhai_raw.split("-", 1)[0].strip()
            token = left.split()[0].strip()
            form_code = token if token else None

    # Prepare result
    result = {
        "company_tax_id": company_tax_id,
        "company_name": company_name,
        "address": address,
        "ma_tb": ma_tb,
        "so_thong_bao": so_thong_bao,
        "ngay_thong_bao": ngay_thong_bao,
        "ma_giaodich": ma_giaodich,
        "tokhai_raw": tokhai_raw,
        "form_raw": tokhai_raw,   # keep backward-compatible key name 'form_raw'
        "form_code": form_code,
        "loai_to_khai": loai_to_khai,
        "ky_thue": ky_thue,
        "lan_nop": lan_nop,
        # accepted only if ma_tb equals '844' (string). normalize if necessary
        "accepted": (str(ma_tb).strip() == "844") if ma_tb else False,
    }

    return result
