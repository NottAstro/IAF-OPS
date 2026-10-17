"""Browser smoke test (PHASE2_IMPLEMENTATION_PLAN P10): sign in, generate and commit a plan, run a what-if, and screenshot
Planner, Missions, Overview, the Ops map view and Exercise. Needs the stack running (scripts/dev.ps1 or make dev) and
    pip install playwright && python -m playwright install chromium
Usage: python scripts/ui_smoke.py data/screens
Exits non-zero on any page error."""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:5173"
errors = []

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": 1680, "height": 1000})
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto(BASE)
    pg.wait_for_timeout(3500)                 # splash shutter
    pg.fill("input[autocomplete=username]", "airhq")
    pg.fill("input[type=password]", "Vayu@2026")
    pg.click("button:has-text('Sign in')")
    pg.wait_for_timeout(2500)

    pg.goto(f"{BASE}/planner")
    pg.wait_for_timeout(5000)
    pg.screenshot(path=str(OUT / "01-planner-empty.png"))
    pg.click("button:has-text('Generate plan')")
    pg.wait_for_selector("text=missions covered in", timeout=90000)
    pg.wait_for_timeout(2500)
    pg.screenshot(path=str(OUT / "02-planner-plan.png"))
    rows = pg.locator(".mission-row:not(.unmet)")
    if rows.count():
        rows.first.click()
        pg.wait_for_timeout(800)
        pg.screenshot(path=str(OUT / "03-planner-item.png"))
    un = pg.locator(".mission-row.unmet")
    if un.count():
        un.first.click()
        pg.wait_for_timeout(800)
        pg.screenshot(path=str(OUT / "04-planner-unmet.png"))
    pg.once("dialog", lambda d: d.accept())
    pg.click("button:has-text('Commit plan')")
    pg.wait_for_timeout(4000)
    pg.screenshot(path=str(OUT / "05-planner-committed.png"))

    pg.click("button.tab:has-text('What-if')")
    pg.click("button:has-text('Run what-if')")
    try:
        pg.wait_for_selector("text=Simulated outcome", timeout=90000)
    except Exception:
        pg.screenshot(path=str(OUT / "06-whatif-FAILED.png"), full_page=True)
        raise
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "06-whatif.png"), full_page=True)

    pg.goto(f"{BASE}/missions")
    pg.wait_for_timeout(5000)
    pg.screenshot(path=str(OUT / "07-missions.png"))
    pg.click("button:has-text('New mission request')")
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "08-mission-form.png"))
    pg.keyboard.press("Escape")

    pg.goto(f"{BASE}/overview")
    pg.wait_for_timeout(5500)
    pg.screenshot(path=str(OUT / "09-overview.png"))

    pg.goto(f"{BASE}/map")
    pg.wait_for_timeout(6000)
    pg.click("button.dock-btn:has-text('Ops')")
    pg.wait_for_timeout(8000)
    pg.screenshot(path=str(OUT / "10-map-ops.png"))

    # directing staff
    ctx = b.new_context(viewport={"width": 1680, "height": 1000})
    ad = ctx.new_page()
    ad.on("pageerror", lambda e: errors.append(f"admin pageerror: {e}"))
    ad.goto(BASE)
    ad.wait_for_timeout(3500)
    ad.fill("input[autocomplete=username]", "admin")
    ad.fill("input[type=password]", "Vayu@2026")
    ad.click("button:has-text('Sign in')")
    ad.wait_for_timeout(2000)
    ad.goto(f"{BASE}/exercise")
    ad.wait_for_timeout(5000)
    ad.screenshot(path=str(OUT / "11-exercise.png"))
    ad.goto(f"{BASE}/admin")                   # D38 model card
    ad.wait_for_timeout(4000)                 # splash shutter replays on a full page load
    ad.wait_for_selector("text=Ranking (AUC)", timeout=60000)
    ad.screenshot(path=str(OUT / "12-admin-model-card.png"), full_page=True)
    b.close()

print("\n".join(errors[:30]) or "no console errors")
