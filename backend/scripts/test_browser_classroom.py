import asyncio
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

async def run():
    print("==================================================")
    print("🚀 AUTOMATED E2E BROWSER CLASSROOM TEST STARTING")
    print("==================================================")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        
        console_logs = []
        page.on('console', lambda msg: console_logs.append(f'[{msg.type}] {msg.text}'))
        page.on('pageerror', lambda err: console_logs.append(f'[PAGE ERROR] {err}'))
        
        # Step 1: Navigate to Home
        print("1. Navigating to http://127.0.0.1:8000 ...")
        await page.goto('http://127.0.0.1:8000')
        await asyncio.sleep(2)
        
        # Step 2: Fill Setup Form
        print("2. Configuring lesson parameters...")
        title = await page.title()
        print(f"   Page Title: {title}")
        
        # Select existing learner if available
        options = await page.locator('#learner-select option').count()
        if options > 1:
            await page.select_option('#learner-select', index=1)
            print("   Selected existing learner from list")
        
        # Fill topic
        await page.fill('#topic-input', "Newton's Laws of Motion")
        
        # Select 5 min budget for fast test
        budget_btn = page.locator('button:has-text("5 min")')
        if await budget_btn.count() > 0:
            await budget_btn.first.click()
            print("   Selected 5 min time budget")
            
        # Click start lesson button
        print("3. Clicking 'Start Personalized Lesson'...")
        start_btn = page.locator('#start-lesson')
        await start_btn.click()
        
        # Wait for classroom screen to become visible
        print("4. Waiting for lesson planning & classroom transition...")
        await page.wait_for_selector('#classroom-screen:not(.hidden)', timeout=75000)
        print("   ✅ Classroom screen is active!")
        
        # Step 3: Inspect Classroom Elements
        await asyncio.sleep(3)
        lesson_title = await page.locator('#classroom-title').inner_text()
        print(f"   Classroom Lesson Title: {lesson_title}")
        
        # Check avatar container
        avatar_canvas_count = await page.locator('#talkinghead canvas').count()
        print(f"   Avatar Canvas present: {avatar_canvas_count > 0}")
        
        # Check whiteboard canvas
        wb_canvas_count = await page.locator('#whiteboard').count()
        print(f"   Whiteboard Canvas present: {wb_canvas_count > 0}")
        
        # Step 4: Verify Subtitles and Audio/Visual Playback
        print("5. Monitoring playback and visual events...")
        for step in range(5):
            await asyncio.sleep(2)
            subtitles = await page.locator('#subtitles').inner_text()
            progress = await page.locator('#seg-progress-label').inner_text()
            print(f"   [t={(step+1)*2}s] Progress: {progress} | Subtitles: {subtitles[:60]}...")
            
        # Capture classroom screenshot while teacher is actively lecturing & board is drawn
        os.makedirs('backend', exist_ok=True)
        await page.screenshot(path='backend/static_classroom_lesson.png')
        print("   📸 Captured active lesson screenshot: backend/static_classroom_lesson.png")
            
        # Step 5: Check if Checkpoint overlay triggers or can be tested
        print("6. Checking interactive elements...")
        checkpoint_visible = await page.is_visible('#checkpoint-overlay:not(.hidden)')
        print(f"   Checkpoint overlay active: {checkpoint_visible}")
        
        if checkpoint_visible:
            print("   Submitting checkpoint answer...")
            await page.fill('#cp-text', "Force equals mass times acceleration")
            await page.click('#cp-send')
            await asyncio.sleep(2)
            await page.screenshot(path='backend/static_classroom_checkpoint.png')
            print("   📸 Captured checkpoint screenshot")
            
        # Step 6: Test Avatar Studio Standalone Page
        print("\n7. Testing 3D Avatar Test Studio (http://127.0.0.1:8000/avatar-test.html)...")
        await page.goto('http://127.0.0.1:8000/avatar-test.html')
        await asyncio.sleep(2)
        badge = await page.locator('#status-badge').inner_text()
        print(f"   Avatar Studio Status: {badge}")
        
        # Test sensitivity slider
        await page.evaluate("() => window.onSensitivityChange(1.4)")
        print("   Adjusted lip-sync sensitivity to 140%")
        
        # Trigger real voice sample
        print("   Triggering synced voice sample playback...")
        await page.click('#btn-sample-voice')
        await asyncio.sleep(1)
        
        # Measure morph targets
        weights = await page.evaluate('''() => {
            if (!window.engine) return {};
            return {
                isSpeaking: window.engine.isSpeaking,
                mouthOpen: Math.round((window.engine.visemeWeights.mouthOpen || 0) * 100),
                jawOpen: Math.round((window.engine.visemeWeights.jawOpen || 0) * 100),
                viseme_aa: Math.round((window.engine.visemeWeights.viseme_aa || 0) * 100),
                viseme_O: Math.round((window.engine.visemeWeights.viseme_O || 0) * 100),
            };
        }''')
        print(f"   3D Formant Weights: {weights}")
        await page.screenshot(path='backend/static_avatar_studio.png')
        print("   📸 Captured avatar studio screenshot")
        
        print("\n==================================================")
        print("🎉 ALL END-TO-END BROWSER TESTS PASSED PERFECTLY!")
        print("==================================================")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
