**English** · [فارسی](README.fa.md)

# Verna Price Widget

Live Iranian market prices on your Windows desktop: Tether, the dollar, gold, coins and crypto, in toman.

<p align="center">
  <img src="docs/list.png" width="230" align="top" alt="Price list">
  &nbsp;
  <img src="docs/chart.png" width="230" align="top" alt="Chart and price alert">
  &nbsp;
  <img src="docs/settings.png" width="230" align="top" alt="Settings">
</p>
<p align="center">
  <img src="docs/story.png" width="300" alt="Compact mode">
</p>

- Collapses to one row while you work and opens under the mouse
- Charts from 6 hours to 5 years, price alerts with Windows notifications
- Coin bubble and Tether / dollar spread, worked out live
- Six Persian fonts, see-through mode, tray icon, start with Windows

## Download

Get `VernaPriceWidget.exe` from the [latest release](https://github.com/VernaTeam/verna-price-widget/releases/latest) and run it.
Needs Windows 10 or 11 with WebView2, and a direct connection from inside Iran.

## From source

```bash
pip install -r requirements.txt
python run.pyw
```

Build the exe with `pyinstaller --noconfirm --clean VernaPriceWidget.spec`, run the tests with `python -m unittest`.

## Credits

Prices from the [Nobitex](https://nobitex.ir) public API and [tgju](https://www.tgju.org) (unofficial).
Fonts: Vazirmatn, Shabnam, Sahel, Samim, Parastoo (Saber Rastikerdar) and Estedad (Amin Abedi), all under the SIL Open Font License.

MIT © 2026 Verna
