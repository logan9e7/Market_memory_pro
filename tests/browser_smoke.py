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
                    page.get_by_role("button",name="Open your desk").click()
                    expect(page.locator('#auth-dialog')).to_be_visible()
                    page.locator('#auth-form [name="username"]').fill("browser-researcher")
                    page.locator('#auth-form [name="email"]').fill("browser-researcher@example.com")
                    page.locator('#auth-form [name="password"]').fill("BrowserSmoke!Strong2026")
                    page.get_by_role("button",name="Create account").click()
                    expect(page.locator('#workspace')).to_be_visible()
                    expect(page.locator('[data-view="overview"]')).to_be_visible()
                    page.get_by_role("button",name="Discovery",exact=True).click()
                    expect(page.locator('[data-view="discovery"]')).to_be_visible()
                    page.locator('#discovery-auto').uncheck()
                    page.locator('[data-discovery-tab="capture"]').click()
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
                    page.locator('[data-discovery-tab="capture"]').click()
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
                    page.locator('[data-discovery-tab="alerts"]').click()
                    page.locator('#alert-form [name="currency"]').select_option("INR")
                    page.locator('#alert-form [name="symbol"]').fill("TCS.NS")
                    page.locator('#alert-form [name="target"]').fill("120")
                    page.get_by_role("button",name="Set alert").click()
                    expect(page.locator('#alerts')).to_contain_text("Watching recorded prices")
                    page.locator('[data-discovery-tab="journal"]').click()
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
                    page.locator('[data-discovery-tab="capture"]').click()
                    page.locator('#quote-form [name="symbol"]').fill("TCS.NS")
                    page.locator('#quote-form [name="price"]').fill("125")
                    page.get_by_role("button",name="Save price & check rules").click()
                    page.locator('[data-discovery-tab="alerts"]').click()
                    expect(page.locator('#alerts')).to_contain_text("Triggered")
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
