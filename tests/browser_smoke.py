"""Optional real-browser smoke test. Requires Playwright and Chromium.

Run with a Python environment containing playwright. Uses the project's venv
to run a separate server and disposable database; never seeds normal user data.
"""
import os
import json
from datetime import datetime, timezone
import sys
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent


def run():
    with tempfile.TemporaryDirectory() as directory:
        with open(Path(directory) / "server.log", "w") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"], cwd=ROOT, env={**{k:v for k,v in os.environ.items() if k not in ("DATABASE_URL", "MARKET_MEMORY_PRODUCTION", "MARKET_MEMORY_REQUIRE_NATIVE_QUANT", "MARKET_MEMORY_MIGRATIONS_AT_STARTUP")}, "MARKET_MEMORY_DB":str(Path(directory) / "browser.sqlite3")}, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen("http://127.0.0.1:8001/health/ready",timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Browser test server did not become ready")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**({"executable_path":os.environ["CHROMIUM_PATH"]} if os.getenv("CHROMIUM_PATH") else {}), args=["--no-sandbox"])
                    context = browser.new_context(viewport={"width":1280,"height":1000})
                    page = context.new_page()
                    errors=[]
                    page.on("pageerror",lambda error:errors.append(str(error)))
                    page.goto("http://127.0.0.1:8001")
                    expect(page.get_by_role("heading",name="Trade less on impulse.",exact=False)).to_be_visible()
                    page.screenshot(path=str(ROOT / 'app-qa-landing-desktop.png'),full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Landing mobile overflow'
                    page.screenshot(path=str(ROOT / 'app-qa-landing-mobile.png'),full_page=True)
                    page.set_viewport_size({'width':1280,'height':1000})
                    page.get_by_role("button",name="Open your desk").click()
                    expect(page.locator('#auth-dialog')).to_be_visible()
                    page.locator('#auth-form [name="username"]').fill("browser-researcher")
                    page.locator('#auth-mode-register').click()
                    page.locator('#auth-form [name="email"]').fill("browser-researcher@example.com")
                    page.locator('#auth-form [name="password"]').fill("BrowserSmoke!Strong2026")
                    page.get_by_role("button",name="Create account").click()
                    expect(page.locator('#workspace')).to_be_visible()
                    expect(page.locator('[data-view="overview"]')).to_be_visible()
                    page.get_by_role("button",name="Discovery",exact=True).click()
                    expect(page.locator('[data-view="discovery"]')).to_be_visible()
                    page.locator('#discovery-auto').uncheck()
                    page.locator('#discovery-tool-select').select_option('capture')
                    # A synthetic quote validates UI behavior without depending on an exchange.
                    page.route("**/api/discovery/prices?*", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"provider":"Test exchange", "quotes":[{"symbol":"BTCUSDT","price":123.45,"currency":"USDT","provider":"Test exchange","as_of":datetime.now(timezone.utc).isoformat(),"change_percent":1,"high":125,"low":120,"volume":10}],"errors":[]})))
                    page.locator('#quote-form [name="symbol"]').fill("BTCUSDT")
                    expect(page.locator('#capture-live-price')).to_contain_text("123.45")
                    page.locator('#capture-use-price').click()
                    expect(page.locator('#quote-form [name="price"]')).to_have_value("123.45")
                    expect(page.locator('#quote-form [name="currency"]')).to_have_value("USDT")
                    page.locator('[data-discovery-tab="markets"]').click()
                    page.locator('#discovery-refresh').click()
                    expect(page.locator('#discovery-results')).to_contain_text("123.45")
                    page.screenshot(path=str(ROOT / "discovery-qa-desktop.png"),full_page=True)
                    page.set_viewport_size({"width":390,"height":844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),"Discovery mobile layout overflows"
                    expect(page.locator('#workspace-mobile-more')).to_be_visible()
                    page.locator('#workspace-mobile-more').select_option('account')
                    expect(page.locator('[data-view="account"]')).to_be_visible()
                    page.get_by_role('button',name='Discovery',exact=True).click()
                    page.screenshot(path=str(ROOT / "discovery-qa-mobile.png"),full_page=True)
                    page.locator('#discovery-results [data-open-asset="BTCUSDT"]').first.click()
                    expect(page.locator('#asset-dialog')).to_be_visible()
                    bounds=page.locator('#asset-dialog').bounding_box()
                    assert abs(bounds['y']+bounds['height']-844)<3,"Asset sheet is not bottom aligned"
                    page.screenshot(path=str(ROOT / "discovery-qa-sheet.png"),full_page=False)
                    page.locator('#asset-close').click()
                    page.set_viewport_size({"width":1280,"height":1000})
                    page.locator('#discovery-results [data-open-asset="BTCUSDT"]').first.click()
                    expect(page.locator('#asset-dialog')).to_be_visible()
                    expect(page.locator('#asset-price')).to_contain_text("123.45")
                    page.locator('#asset-watch').click()
                    expect(page.locator('#asset-feedback')).to_contain_text("Added")
                    page.locator('#asset-capture').click()
                    page.locator('#asset-capture-form [name="note"]').fill("Capture from asset popup")
                    page.locator('#asset-capture-form').get_by_role('button',name='Save capture').click()
                    expect(page.locator('#notice')).to_have_text("Capture saved to Memory.")
                    page.locator('#discovery-results [data-open-asset="BTCUSDT"]').first.click()
                    page.locator('#asset-alert').click()
                    expect(page.locator('#alert-form [name="symbol"]')).to_have_value("BTCUSDT")
                    expect(page.locator('#alert-form [name="currency"]')).to_have_value("USDT")
                    page.locator('#discovery-manual-capture').click()
                    manual=page.locator('#asset-capture-form')
                    manual.locator('[name="symbol"]').fill("MANUAL")
                    manual.locator('[name="currency"]').select_option("INR")
                    manual.locator('[name="price"]').fill("42")
                    manual.locator('[name="note"]').fill("Independent manual capture")
                    manual.get_by_role('button',name='Save capture').click()
                    expect(page.locator('#notice')).to_have_text("Capture saved to Memory.")
                    page.locator('#discovery-tool-select').select_option('capture')
                    page.unroute("**/api/discovery/prices?*")
                    page.locator('#quote-form [name="currency"]').select_option("INR")
                    page.locator('#quote-form [name="symbol"]').fill("TCS.NS")
                    page.locator('#quote-form [name="price"]').fill("110")
                    page.get_by_role("button",name="Save price & check rules").click()
                    expect(page.locator('#quotes')).to_contain_text("TCS.NS")
                    page.locator('#snapshot-form [name="symbol"]').fill("TCS.NS")
                    page.locator('#snapshot-form [name="note"]').fill('<img src=x onerror="alert(1)"> user note')
                    page.get_by_role("button",name="Keep this moment").click()
                    expect(page.locator('#notice')).to_have_text("Snapshot preserved.")
                    page.locator('#discovery-tool-select').select_option('alerts')
                    page.locator('#alert-form [name="currency"]').select_option("INR")
                    page.locator('#alert-form [name="symbol"]').fill("TCS.NS")
                    page.locator('#alert-form [name="target"]').fill("120")
                    page.get_by_role("button",name="Set alert").click()
                    expect(page.locator('#alerts')).to_contain_text("Watching recorded prices")
                    page.locator('#discovery-tool-select').select_option('journal')
                    form=page.locator('#decision-form')
                    for name,value in {"symbol":"TCS.NS","setup":"breakout","price":"101","trigger_price":"100","note":"Observed breakout; user-reviewed evidence."}.items():
                        form.locator(f'[name="{name}"]').fill(value)
                    page.get_by_role("button",name="Record decision",exact=True).click()
                    expect(page.locator('#notice')).to_have_text("Decision saved. Review it when the outcome is known.")
                    for index in range(1,10):
                        result=context.request.post("http://127.0.0.1:8001/api/decisions",data={"symbol":"TCS.NS","currency":"INR","price":101,"setup":"breakout","side":"buy","condition":"above","trigger_price":100,"note":"Observed breakout; user-reviewed evidence.","request_id":f"browser-decision-{index}"})
                        assert result.status==201,result.text()
                    page.reload()
                    page.get_by_role("button",name="Memory",exact=True).click()
                    expect(page.locator('#snapshots')).to_contain_text('<img src=x onerror="alert(1)"> user note')
                    assert page.locator('#snapshots img').count()==0,"User note became HTML"
                    for index in range(10):
                        review=page.locator('.review-form').first
                        review.locator("..").locator("summary").click()
                        expect(review).to_be_visible()
                        review.locator('[name="outcome"]').select_option("loss" if index<3 else "win")
                        review.locator('[name="lesson"]').fill("Completed outcome; preserve the original reasoning.")
                        with page.expect_response(lambda response:'/review' in response.url and response.request.method=='POST') as response:
                            review.get_by_role("button",name="Complete review").click()
                        assert response.value.status==200
                        expect(page.locator('.review-form')).to_have_count(9-index)
                    page.get_by_role("button",name="Strategies",exact=True).click()
                    expect(page.locator('#strategies')).to_contain_text("70%")
                    expect(page.locator('#strategies')).to_contain_text("Qualified by historical evidence")
                    page.locator('[data-tab="opportunities"]').click()
                    expect(page.locator('#opportunities')).to_contain_text("pending")
                    assert context.request.get("http://127.0.0.1:8001/api/state").json()["paper_orders"]==[]
                    page.get_by_role("button",name="Approve paper execution").click()
                    expect(page.locator('#orders')).to_contain_text("BUY TCS.NS")
                    assert len(context.request.get("http://127.0.0.1:8001/api/state").json()["paper_orders"])==1
                    page.locator('[data-tab="discovery"]').click()
                    page.locator('#discovery-tool-select').select_option('capture')
                    page.locator('#quote-form [name="symbol"]').fill("TCS.NS")
                    page.locator('#quote-form [name="price"]').fill("125")
                    page.get_by_role("button",name="Save price & check rules").click()
                    page.locator('#discovery-tool-select').select_option('alerts')
                    expect(page.locator('#alerts')).to_contain_text("Triggered")
                    page.locator('[data-tab="memory"]').click()
                    page.locator('#memory-search').fill('NO-MATCH-ASSET')
                    expect(page.locator('#memory-summary')).to_contain_text('No decisions match')
                    page.locator('#memory-search').fill('')
                    page.locator('#memory-tab-captures').click()
                    expect(page.locator('#capture-summary')).to_contain_text('matching captures')
                    page.locator('#memory-tab-decisions').click()
                    page.locator('[data-tab="lab"]').click()
                    page.locator('[data-workspace-switch="lab:new"]').click()
                    lab=page.locator('#lab-form')
                    lab.locator('[name="title"]').fill('Volume confirmation')
                    lab.locator('[name="symbol"]').fill('BTCUSDT')
                    lab.locator('[name="hypothesis"]').fill('A support retest may hold when volume expands; validate against comparable entries.')
                    lab.get_by_role('button',name='Save private draft').click()
                    expect(page.locator('#lab-ideas')).to_contain_text('Volume confirmation')
                    page.locator('#lab-ideas details').last.locator('summary').click()
                    page.locator('#lab-ideas [name="content"]').fill('Check the journal evidence before testing this setup.')
                    page.locator('#lab-ideas').get_by_role('button',name='Save note').click()
                    expect(page.locator('#lab-ideas')).to_contain_text('Check the journal evidence')
                    page.locator('[data-tab="quant"]').click()
                    page.locator('#quant-trades [name="returns"]').fill('2, -1, 3, -1, 1')
                    page.locator('#quant-trades').get_by_role('button').click()
                    expect(page.locator('#trade-result')).to_contain_text('Observed win rate')
                    expect(page.locator('#trade-result')).to_contain_text('60%')
                    page.locator('#quant-tab-options').click()
                    page.locator('#quant-option').get_by_role('button').click()
                    expect(page.locator('#option-result')).to_contain_text('Theoretical price')
                    page.locator('#quant-tab-statistics').click()
                    page.route('**/api/intelligence/analyze',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'id':1,'analysis':{'level_1_evidence':[{'parameter':'Recorded evidence','observation':'Synthetic UI test report grounded in a journal reference.','confidence':0.5,'evidence_ids':['decision:1']}],'limitations':['Synthetic browser-test report.']}})))
                    page.route('**/api/intelligence/evolution',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'status':'insufficient_history'})))
                    page.locator('[data-tab="intelligence"]').click()
                    page.locator('#analyze-memory').click()
                    expect(page.locator('#intelligence-result')).to_contain_text('Your evidence review')
                    page.locator('[data-tab="account"]').click()
                    expect(page.locator('#account-name')).to_have_text('browser-researcher')
                    page.locator('#account-tab-sessions').click()
                    expect(page.locator('#logout-all')).to_be_visible()
                    page.locator('#account-tab-security').click()
                    page.locator('[data-tab="opportunities"]').click()
                    page.locator('#inbox-tab-history').click()
                    expect(page.locator('#orders')).to_contain_text('BUY TCS.NS')
                    views=['overview','memory','strategies','lab','quant','intelligence','account','opportunities','discovery']
                    for view in views:
                        page.locator('[data-tab="'+view+'"]').click()
                        expect(page.locator('[data-view="'+view+'"]').first).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),view+' desktop overflow'
                        page.screenshot(path=str(ROOT / ('app-qa-'+view+'-desktop.png')),full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    for view in views:
                        if view in ['overview','memory','discovery']:
                            page.locator('[data-tab="'+view+'"]').click()
                        else:
                            page.locator('#workspace-mobile-more').select_option(view)
                        expect(page.locator('[data-view="'+view+'"]').first).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),view+' mobile overflow'
                        page.screenshot(path=str(ROOT / ('app-qa-'+view+'-mobile.png')),full_page=True)
                    page.set_viewport_size({'width':1280,'height':1000})
                    # A genuine hidden-tab event captures the close visit.
                    other=context.new_page()
                    other.goto("about:blank")
                    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
                    for _ in range(30):
                        if any(v["kind"]=="close" for v in context.request.get("http://127.0.0.1:8001/api/state").json()["visits"]):
                            break
                        time.sleep(.1)
                    else:
                        raise AssertionError("Close visit was not persisted")
                    page.bring_to_front()
                    page.screenshot(path=str(ROOT / "browser-smoke.png"),full_page=True)
                    page.set_viewport_size({"width":390,"height":844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),"Mobile layout overflows"
                    page.get_by_role("button",name="Sign out").click()
                    expect(page.locator('#auth')).to_be_visible()
                    page.get_by_role("button",name="Open your desk").click()
                    page.locator('#auth-form [name="username"]').fill("browser-researcher")
                    page.locator('#auth-form [name="password"]').fill("BrowserSmoke!Strong2026")
                    page.get_by_role("button",name="Sign in",exact=True).last.click()
                    expect(page.locator('#workspace')).to_be_visible()
                    expect(page.locator('#metrics')).to_contain_text("Decisions logged")
                    page.get_by_role("button",name="Memory",exact=True).click()
                    expect(page.locator('#decisions')).to_contain_text("TCS.NS")
                    assert not errors,errors
                    browser.close()
                    print("Browser workflow passed: themed landing, modal registration, overview, capture, safe snapshot text, journal, 70% evidence, explicit paper approval, alert, close visit, mobile layout, logout, login and persistence.")
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    run()
