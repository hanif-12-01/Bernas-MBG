# Bernas MBG - Multi Dashboard PoC

Proof of Concept (PoC) aplikasi Bernas MBG berbasis dashboard terpisah untuk berbagai peran: Vendor, Guru, Murid, Wali Murid, Pemda, dan Super Admin.

Aplikasi ini dibuat sebagai simulasi alur MBG dari unggah menu oleh vendor sampai validasi, eskalasi keluhan, dan kontrol pencairan BOSP.

## Demo Entry Point

- `index.html` sebagai launcher semua dashboard.
- Halaman app berada di folder `apps/`.

## Struktur Proyek

```text
.
|-- index.html
|-- DOKUMENTASI_SCREENSHOT_PROPOSAL.txt
`-- apps/
    |-- vendor.html
    |-- guru.html
    |-- murid.html
    |-- wali.html
    |-- pemda.html
    `-- super_admin.html
```

## Teknologi

- HTML single-file per dashboard
- React 18 (UMD) + ReactDOM
- Babel Standalone (`text/babel`)
- Tailwind CSS via CDN
- LocalStorage untuk state bersama antar dashboard

## Kunci State Bersama

Dashboard menggunakan localStorage sebagai media sinkronisasi data antar peran:

- `mbg_poc_state_v1`: state utama proses MBG
- `mbg_sso_session`: simulasi sesi login multi-peran

## Ringkasan Fitur Per Dashboard

### 1) Vendor (`apps/vendor.html`)

- Upload menu/foto harian SPPG.
- Update progres operasional:
  - `FotoDiunggahSPPG`
  - `DalamPengiriman`
  - `TibaDiSekolah`
- Menulis log aktivitas yang bisa dipantau dashboard lain.

### 2) Guru (`apps/guru.html`)

- Melakukan 2 scan wajib (kedatangan vendor + validasi makanan aktual).
- Simulasi validasi YOLO status `valid` atau `tidak_sesuai`.
- Menerbitkan E-BAST jika syarat terpenuhi.
- Menahan E-BAST/BOSP otomatis jika ada indikasi masalah (keluhan kritis atau hasil scan tidak sesuai).

### 3) Murid (`apps/murid.html`)

- Melihat status menu harian dan progres MBG.
- Mengirim keluhan/aspirasi.
- Keluhan dengan kata kunci kritis akan memicu red alert dan menahan E-BAST/BOSP.
- Melihat riwayat keluhan yang pernah dikirim.

### 4) Wali Murid (`apps/wali.html`)

- Login peran wali murid.
- Menyampaikan keluhan/validasi publik terkait kualitas layanan MBG.
- Ikut berkontribusi pada data keluhan yang dipantau Pemda.

### 5) Pemda (`apps/pemda.html`)

- Command center monitoring status MBG lintas peran.
- Modul red alert, cross-validation keluhan, dan simulasi keamanan pangan.
- Tracker progres vendor.
- Auto-rapor dan narasi rekomendasi berbasis data simulasi.
- Kontrol keputusan pencairan BOSP (`tahan` atau `lanjutkan`).

### 6) Super Admin (`apps/super_admin.html`)

- Monitoring umum sistem dan operasional.
- Manajemen user dan role/permission.
- Master data dan operational status.
- Log sistem dan simulasi backup.

## Alur Simulasi Utama

1. Vendor upload menu/foto dan ubah status pengiriman.
2. Guru melakukan scan wajib dan validasi kualitas.
3. Murid/Wali dapat mengirim keluhan.
4. Pemda memantau alert, membaca pola keluhan, dan menentukan kontrol BOSP.
5. Super Admin memantau health sistem, user, role, dan konfigurasi.

## Cara Menjalankan

Karena ini aplikasi statis, jalankan dengan local web server.

Contoh cepat:

1. Buka folder proyek.
2. Jalankan Live Server (VS Code) atau server statis lain.
3. Akses `http://localhost:5500` lalu buka `index.html`.

## Catatan PoC

- Fokus utama adalah validasi alur bisnis dan pengalaman dashboard lintas peran.
- Belum menggunakan backend production, database, autentikasi real, atau integrasi AI/model production.
- Data bersifat simulasi dan disimpan lokal di browser.

## Rencana Pengembangan Lanjutan

- Integrasi backend API untuk state terpusat.
- Autentikasi RBAC berbasis token.
- Integrasi model AI/vision dan NLP service production.
- Audit trail dan observability end-to-end.
- Hardening keamanan dan pengujian otomatis.
