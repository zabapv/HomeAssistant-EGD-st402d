# EG.D Meter ST402D – Home Assistant

Neoficiální integrace pro Home Assistant, která zobrazuje údaje elektroměru EG.D přenášené přes RS-485 a TCP převodník USR-DR164. Nastavuje se v uživatelském rozhraní Home Assistantu.

## Funkce

- Okamžitý odběr a dodávka celkem i na fázích L1–L3 (W).
- Kumulativní odběr celkem a v tarifech T1–T4 a celková dodávka (kWh).
- Aktivní tarif, sériové číslo, stav spojení a čas posledního měření.
- Energetické senzory jsou určeny pro dlouhodobé statistiky a Energy Dashboard.

## Požadavky

- Home Assistant Core 2026.11 nebo novější.
- Elektroměr EG.D s aktivním předáváním měřených dat přes RS-485.
- TCP převodník dostupný z Home Assistantu; výchozí port je 5000.

## Instalace

### HACS / Marketplace

V HACS otevřete vlastní repozitáře a přidejte `https://github.com/zabapv/HomeAssistant-EGD-st402d` jako integraci. Poté ji nainstalujte a restartujte Home Assistant.

### Ruční instalace

Stáhněte repozitář a zkopírujte adresář `custom_components/egd_meter` do `config/custom_components/egd_meter`. Restartujte Home Assistant.

## Konfigurace

V Home Assistantu přidejte integraci **EG.D Meter ST402D**. Zadejte IP adresu nebo název TCP převodníku, port a název zařízení. První měření může dorazit až za 60 sekund. Pokud měření není dostupné, senzory zůstanou nedostupné; chybějící údaj se nezobrazuje jako nula.

Jednotky vycházejí z dokumentace elektroměru. Po instalaci porovnejte zobrazené hodnoty s displejem měřidla.

## Licence

Tento projekt je vydán pod licencí [MIT](LICENSE). Integrace není oficiálně spojena se společností EG.D.
