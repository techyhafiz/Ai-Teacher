import asyncio
from playwright.async_api import async_playwright

async def run_test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 800})
        
        console_logs = []
        page.on('console', lambda m: console_logs.append(m.text))
        page.on('pageerror', lambda e: print('PAGE ERROR:', e))

        print("1. Loading AI Teacher classroom at http://127.0.0.1:8000...")
        await page.goto('http://127.0.0.1:8000')
        await asyncio.sleep(2)

        # 2. Setup lesson: Enter topic
        print("2. Entering topic: Ohms Law and Circuit Analysis...")
        await page.fill('#topic-input', "Ohms Law and Circuit Analysis")
        await page.click('#start-lesson')

        # Wait for classroom screen to become active
        print("3. Waiting for classroom to launch...")
        try:
            await page.wait_for_selector('#classroom-screen:not(.hidden)', timeout=35000)
            print("   Classroom screen is active!")
        except Exception as e:
            print("   Timeout waiting for classroom transition:", e)
            await page.screenshot(path='backend/static_classroom_timeout.png')
            await browser.close()
            return

        # Give classroom audio and timeline 10 seconds to play and render circuit
        print("4. Allowing audio and whiteboard timeline to execute (10s)...")
        await asyncio.sleep(10)

        # 4. Check Avatar Posture and Bone Rotations in live classroom
        avatar_status = await page.evaluate('''() => {
            const container = document.getElementById('talkinghead');
            const hasCanvas = !!document.querySelector('#talkinghead canvas');
            const subtitles = document.getElementById('subtitles')?.textContent || '';
            const overlay = document.getElementById('board-overlay');
            const equationCards = overlay ? overlay.querySelectorAll('.board-equation-card').length : 0;
            const whiteboardCanvas = document.getElementById('whiteboard');
            
            return {
                hasCanvas,
                subtitles,
                equationCards,
                whiteboardWidth: whiteboardCanvas?.width,
                whiteboardHeight: whiteboardCanvas?.height
            };
        }''')
        print("4. Classroom Status:", avatar_status)

        # 5. Capture full classroom screenshot
        await page.screenshot(path='backend/static_classroom_ohms_law.png')
        print("Captured static_classroom_ohms_law.png")

        # Print relevant console logs
        wb_logs = [l for l in console_logs if '[Whiteboard]' in l or 'avatar' in l.lower() or 'audio' in l.lower()]
        print("5. Relevant Console Logs:")
        for l in wb_logs[:12]:
            print("  ", l)

        await browser.close()

if __name__ == '__main__':
    asyncio.run(run_test())
