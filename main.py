#!/usr/bin/env python
"""
Vehicle Mobile API Flask App for Cloud / VPS deployment
"""

import sys, os, subprocess, importlib, shutil, re, time, threading
from flask import Flask, request, jsonify
import warnings
import requests as _reqs

warnings.filterwarnings("ignore", category=_reqs.packages.urllib3.exceptions.InsecureRequestWarning)

HP = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml?statecd=Mzc2MzM2MzAzNjY0MzIzODM3NjIzNjY0MzY2MjM3NDQ0Yw=="
HB = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml"
LI = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/usermgmt/login.xhtml"
FR = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/balanceservice/form_reschedule_fitness.xhtml"
SMC_API_URL = "https://www.smcinsurance.com/central/centralcall/CallReqWithHeader"
TIMEOUT = 10

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}
AJAX_HEADERS = {
    "Accept": "application/xml, text/xml, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded",
    "Faces-Request": "partial/ajax",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://vahan.parivahan.gov.in"
}

def build_session():
    sess = _reqs.Session()
    sess.headers.update(BASE_HEADERS)
    sess.verify = False
    adapter = _reqs.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=1)
    sess.mount("https://", adapter)
    return sess

def _req(sess, url, data=None, headers=None, referer=None):
    hdrs = {}
    if headers: hdrs.update(headers)
    if referer: hdrs["Referer"] = referer
    if data is not None:
        resp = sess.post(url, data=data, headers=hdrs, timeout=TIMEOUT)
    else:
        resp = sess.get(url, headers=hdrs, timeout=TIMEOUT)
    return resp.text, dict(resp.headers)

def _extract_vs(html):
    m = re.search(r'<input[^>]*name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None

def _extract_vs_ajax(html):
    m = re.search(r'<update id="j_id1:javax\.faces\.ViewState:0"><!\[CDATA\[(.*?)\]\]></update>', html)
    return m.group(1) if m else None

_smc_sess = None
_smc_primed = False

def _get_smc_sess():
    global _smc_sess, _smc_primed
    if _smc_sess is None:
        s = _reqs.Session()
        s.headers.update({"User-Agent": "okhttp/4.9.2"})
        s.verify = False
        adapter = _reqs.adapters.HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=0)
        s.mount("https://", adapter)
        _smc_sess = s
    if not _smc_primed:
        try:
            _smc_sess.post(SMC_API_URL, json={"url": "GetVaahanDetailsByVehicleNo", "props": ["", "", "0"]}, timeout=5)
        except Exception:
            pass
        _smc_primed = True
    return _smc_sess

def _fetch_vehicle_smc(reg_no):
    sess = _get_smc_sess()
    resp = sess.post(SMC_API_URL, json={"url": "GetVaahanDetailsByVehicleNo", "props": [reg_no, "", "0"]}, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"SMC API HTTP {resp.status_code}")
    data = resp.json()
    if data.get("statusCode") == 200 and data.get("response"):
        return data["response"]
    raise Exception(f"SMC API failed: {data.get('statusMessage', 'unknown error')}")

def get_mobile(reg_no, chassis_no_last5=None):
    start = time.time()
    result = {"success": False, "mobile_number": "", "chassis_number": "", "engine_number": "",
              "error": "", "response_time_seconds": 0}
    try:
        if not chassis_no_last5:
            smc_data = _fetch_vehicle_smc(reg_no)
            chassis_full = smc_data.get("chassis", "").replace(" ", "")
            engine_no = smc_data.get("engine", "")
            chassis_no_last5 = chassis_full[-5:]
            result["chassis_number"] = chassis_full
            result["engine_number"] = engine_no
            
        sess = build_session()
        html, _ = _req(sess, HP)
        vs = _extract_vs(html)
        if not vs:
            raise Exception("No ViewState in homepage (Parivahan WAF Block)")
            
        cid = "j_idt193"
        cid_match = re.search(r'<div[^>]*id="(j_idt\d+)"[^>]*class="[^"]*ui-chkbox', html)
        if cid_match:
            cid = cid_match.group(1)
            
        ajax_h = dict(AJAX_HEADERS)
        ajax_h["Referer"] = HP
        
        # Step 1
        form = {"javax.faces.partial.ajax": "true", "homepageformid": "homepageformid", "javax.faces.ViewState": vs,
                "javax.faces.source": "fit_c_office_to", "javax.faces.partial.execute": "fit_c_office_to",
                "javax.faces.behavior.event": "change", "javax.faces.partial.event": "change", "fit_c_office_to_input": "1"}
        html, _ = _req(sess, HB, data=form, headers=ajax_h)
        vs = _extract_vs_ajax(html) or vs
        
        # Step 2
        form = {"javax.faces.partial.ajax": "true", "homepageformid": "homepageformid", "javax.faces.ViewState": vs,
                "javax.faces.source": cid, "javax.faces.partial.execute": cid, "javax.faces.partial.render": "proccedHomeButtonId",
                "javax.faces.behavior.event": "change", f"{cid}_input": "on"}
        html, _ = _req(sess, HB, data=form, headers=ajax_h)
        vs = _extract_vs_ajax(html) or vs
        
        # Step 3
        form = {"javax.faces.partial.ajax": "true", "homepageformid": "homepageformid", "javax.faces.ViewState": vs,
                "javax.faces.source": "proccedHomeButtonId", "javax.faces.partial.execute": "@all",
                "proccedHomeButtonId": "proccedHomeButtonId", f"{cid}_input": "on"}
        html, _ = _req(sess, HB, data=form, headers=ajax_h)
        vs = _extract_vs_ajax(html) or vs
        
        dlg = "j_idt536"
        dlg_match = re.search(r'id="(j_idt\d+)"[^>]*class="[^"]*ui-button', html)
        if dlg_match:
            dlg = dlg_match.group(1)
            
        form = {"javax.faces.partial.ajax": "true", "homepageformid": "homepageformid", "javax.faces.ViewState": vs,
                "javax.faces.source": dlg, "javax.faces.partial.execute": "@all", dlg: dlg, f"{cid}_input": "on"}
        html, _ = _req(sess, HB, data=form, headers=ajax_h)
        vs = _extract_vs_ajax(html) or vs
        
        # Login & Fitness
        html, _ = _req(sess, LI + "?faces-redirect=true", referer=HP)
        vs = _extract_vs(html)
        if vs:
            fit = "j_idt506"
            fit_match = re.search(r'id="(j_idt\d+)"[^>]*name="\1"[^>]*type="submit"', html)
            if fit_match:
                fit = fit_match.group(1)
            html, _ = _req(sess, LI, data={"loginForm": "loginForm", fit: fit, "javax.faces.ViewState": vs,
                                           "fitbalcTest": "fitbalcTest", "pur_cd": "86"},
                           headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://vahan.parivahan.gov.in"},
                           referer=LI + "?faces-redirect=true")
            html, _ = _req(sess, FR, referer=LI + "?faces-redirect=true")
            vs = _extract_vs(html)
            if vs:
                ajax_h["Referer"] = FR
                html, _ = _req(sess, FR, data={
                    "javax.faces.partial.ajax": "true", "javax.faces.source": "balanceFeesFine:validate_dtls",
                    "javax.faces.partial.execute": "@all", "javax.faces.partial.render": "balanceFeesFine:auth_panel",
                    "balanceFeesFine:validate_dtls": "balanceFeesFine:validate_dtls", "balanceFeesFine": "balanceFeesFine",
                    "balanceFeesFine:tf_reg_no": reg_no, "balanceFeesFine:tf_chasis_no": chassis_no_last5, "javax.faces.ViewState": vs
                }, headers=ajax_h)
                
                mobile = None
                nums = re.findall(r'\b[6-9]\d{9}\b', html)
                if nums:
                    mobile = nums[0]
                if mobile:
                    result["success"] = True
                    result["mobile_number"] = mobile
                else:
                    result["error"] = "Mobile number not found in final response"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        
    result["response_time_seconds"] = round(time.time() - start, 2)
    return result

app = Flask(__name__)

@app.after_request
def _add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
def _index():
    return jsonify({"name": "Vehicle Mobile API", "version": "1.0", "usage": "/api/mobile?vehicle=KL41V3504"})

@app.route("/api/mobile", methods=["GET", "POST"])
def _api_mobile():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        vehicle = data.get("vehicle_number", data.get("vehicle", "")).upper().strip()
        chassis = data.get("chassis_last5", data.get("chassis", "")) or None
    else:
        vehicle = request.args.get("vehicle", "").upper().strip()
        chassis = request.args.get("chassis", "").strip() or None

    if not vehicle or len(vehicle) < 6:
        return jsonify({"success": False, "error": "Valid vehicle number required"}), 400

    result = get_mobile(vehicle, chassis)
    if not result.get("error"): result.pop("error", None)
    if not result.get("chassis_number"): result.pop("chassis_number", None)
    if not result.get("engine_number"): result.pop("engine_number", None)
    
    return jsonify(result), (200 if result.get("success") else 400)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
