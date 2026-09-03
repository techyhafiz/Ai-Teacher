import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright

async def main():
    print("Testing live whiteboard rendering in browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 800})
        await page.goto('http://127.0.0.1:8000')
        await asyncio.sleep(1)
        
        # Switch to classroom screen directly in DOM to test board
        await page.evaluate(r'''() => {
            document.getElementById('setup-screen').classList.add('hidden');
            document.getElementById('classroom-screen').classList.remove('hidden');
            document.getElementById('classroom-title').textContent = "Ohm's Law & Circuit Analysis";
            
            Whiteboard.init(document.getElementById('whiteboard'));
            
            // Draw circuit diagram
            Whiteboard.execute('draw_diagram', {
                title: "Complete Series Circuit",
                clear_first: true,
                shapes: [
                    { kind: "battery", x: 18, y: 50, voltage: 12, label: "12V Battery", chalk: "yellow" },
                    { kind: "wire", points: [18, 38, 18, 20, 82, 20, 82, 38], chalk: "blue" },
                    { kind: "resistor", x: 82, y: 50, label: "R1 = 6 Ω", chalk: "pink" },
                    { kind: "wire", points: [82, 62, 82, 80, 18, 80, 18, 62], chalk: "blue" },
                    { kind: "arrow", x: 45, y: 20, x2: 58, y2: 20, label: "Current I = 2.0 A →", chalk: "green" },
                    { kind: "voltmeter", x: 50, y: 50, label: "V = 12V", chalk: "yellow" }
                ]
            });
            
            // Draw KaTeX equation with properly escaped LaTeX
            Whiteboard.execute('draw_equation', {
                latex: String.raw`V = I \times R \implies I = \frac{V}{R} = \frac{12\text{ V}}{6\,\Omega} = 2.0\text{ A}`,
                label: "Ohm's Law Formula",
                position: "bottom",
                chalk: "yellow"
            });
        }''')
        
        await asyncio.sleep(2)
        await page.screenshot(path='backend/static_classroom_whiteboard.png')
        print("📸 Captured static_classroom_whiteboard.png")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
