# Albion DPS Meter

Partindeki herkesin verdiği hasarı, heal'i ve aldığı hasarı savaş savaş kaydeder.
Sonuçları panelin **DPS Meter** sekmesinde görürsün.

## Nasıl çalışır

- `albion_dps.py` bilgisayarında çalışır, Albion'un ağ trafiğini **sadece okur**.
  Oyuna hiçbir şey göndermez, oyun dosyalarına dokunmaz.
- Sadece kendi partini sayar (partide değilsen sadece seni).
- Oturum sen paneldeki **Bitir ve kaydet** düğmesine basana kadar sürer (bölge değişse,
  program kapanıp açılsa bile). Bitirince geçmişe kaydedilir.
- Hasar/heal'in yanında kendi kazandığın fame, combat fame credit, silver, might, favor ve
  faction puanını da sayar. Combat fame credit, oyunun Destiny Board'da 100 olmuş
  düğümler için verdiği kredidir; değeri doğrudan oyundan okunur (ReSpec boost
  açıksa onun etkisi ve ödenen silver da dahil).
- Kayıtlar `kayitlar` klasöründe durur. Panel bunları `http://127.0.0.1:47700`
  adresinden okur; bu adres sadece senin bilgisayarından erişilebilir.
- Destiny Board kayıt modu (geliştirme): oyunun board mesajları ham olarak
  `destiny-kayit` klasörüne yazılır. Bu dosyalar board'u otomatik okumayı çözmek için
  kullanılır; sadece senin bilgisayarında durur, bir yere gönderilmez.

## Kurulum (bir kere)

1. **Npcap** kur: https://npcap.com/#download (varsayılan ayarlarla).
2. **AlbionDPSMeter.exe** indir:
   https://github.com/cagroren/albion-craft-planner/releases/latest/download/AlbionDPSMeter.exe
   Python gerekmez. Windows uyarı verirse "Ek bilgi" → "Yine de çalıştır".

## Kullanım

1. `AlbionDPSMeter.exe` dosyasına çift tıkla. Siyah pencere açık kalsın,
   panel tarayıcıda kendiliğinden açılır.
2. Albion'a gir. En iyisi toplayıcıyı karakter seçim ekranındayken başlatmak,
   böylece parti bilgisini baştan görür.

Python kuruluysa exe yerine `DPS Meter Baslat.bat` ile kaynak koddan da çalıştırabilirsin.

## Exe'yi yeniden derlemek (geliştirici için)

    py -3 -m pip install pyinstaller scapy pillow
    py -3 -m PyInstaller --onefile --console --name AlbionDPSMeter --collect-submodules scapy.layers albion_dps.py

## Sorun çözme

- **Panel "Bağlı değil" diyor:** siyah pencere açık mı? Tarayıcı "yerel ağdaki
  cihazlara erişim" izni sorduysa İzin ver.
- **"Oyun bekleniyor"da kalıyor:** Npcap kurulu mu? VPN/çoklu ağ kartı varsa
  pencerede yazan ağ kartı yanlış olabilir.
- **Oyun güncellemesinden sonra veri gelmiyor:** program açılışta güncel olay
  kodlarını kendisi çekiyor; birkaç gün içinde düzelmezse protokol değişmiş olabilir.

Protokol çözümü, açık kaynak AlbionOnline-StatisticsAnalysis (GPL-3.0)
projesinin kaynak kodu incelenerek Python'a uyarlanmıştır.
