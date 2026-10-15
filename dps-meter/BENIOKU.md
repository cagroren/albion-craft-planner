# Albion DPS Meter

Partindeki herkesin verdiği hasarı, heal'i ve aldığı hasarı savaş savaş kaydeder.
Sonuçları panelin **DPS Meter** sekmesinde görürsün.

## Nasıl çalışır

- `albion_dps.py` bilgisayarında çalışır, Albion'un ağ trafiğini **sadece okur**.
  Oyuna hiçbir şey göndermez, oyun dosyalarına dokunmaz.
- Sadece kendi partini sayar (partide değilsen sadece seni).
- Oturum sen paneldeki **Bitir ve kaydet** düğmesine basana kadar sürer (bölge değişse,
  program kapanıp açılsa bile). Bitirince geçmişe kaydedilir.
- Hasar/heal'in yanında kendi kazandığın fame, combat fame, silver, might, favor ve
  faction puanını da sayar.
- Kayıtlar `kayitlar` klasöründe durur. Panel bunları `http://127.0.0.1:47700`
  adresinden okur; bu adres sadece senin bilgisayarından erişilebilir.

## Kurulum (bir kere)

1. **Npcap** kur: https://npcap.com/#download (varsayılan ayarlarla).
2. **Python** kurulu değilse kur: https://www.python.org/downloads/
   (kurarken "Add python.exe to PATH" kutusunu işaretle).

## Kullanım

1. `DPS Meter Baslat.bat` dosyasına çift tıkla. Siyah pencere açık kalsın.
   İlk açılışta gerekli paketi (scapy) kendisi kurar.
2. Albion'a gir. En iyisi toplayıcıyı karakter seçim ekranındayken başlatmak,
   böylece parti bilgisini baştan görür.
3. Panelde **DPS Meter** sekmesini aç.

## Sorun çözme

- **Panel "Bağlı değil" diyor:** siyah pencere açık mı? Tarayıcı "yerel ağdaki
  cihazlara erişim" izni sorduysa İzin ver.
- **"Oyun bekleniyor"da kalıyor:** Npcap kurulu mu? VPN/çoklu ağ kartı varsa
  pencerede yazan ağ kartı yanlış olabilir.
- **Oyun güncellemesinden sonra veri gelmiyor:** program açılışta güncel olay
  kodlarını kendisi çekiyor; birkaç gün içinde düzelmezse protokol değişmiş olabilir.

Protokol çözümü, açık kaynak AlbionOnline-StatisticsAnalysis (GPL-3.0)
projesinin kaynak kodu incelenerek Python'a uyarlanmıştır.
