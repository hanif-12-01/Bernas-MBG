# Bernas-MBG (GiziOptima) — Adaptive Kitchen Operations & Procurement Recovery Engine

> **Peringatan Penting (`DEMO_ONLY` / Simulasi Teknis):** Seluruh data bawaan dan fixture uji bersifat **sintetis untuk demonstrasi teknis**. Aplikasi ini adalah sistem pendukung keputusan operasional internal dapur SPPG dan **bukan** pengganti validasi ahli gizi klinis, uji laboratorium/BPOM, sertifikasi halal/SLHS, ataupun sistem resmi BGN/SIPGN.

**Bernas-MBG (`GiziOptima`)** menggantikan PoC dashboard HTML statis awal dengan platform full-stack persisten berbasis **Next.js 15 + FastAPI + SQLAlchemy/Alembic + PuLP/CBC MILP** untuk perencanaan menu MBG berbasis resep terverifikasi, pengawasan kualitas stok per lot, penanganan insiden bahan bermasalah (*Safety Hold*), pemulihan gangguan minim perubahan (*Minimum-Disruption Optimization*), serta verifikasi visual menu berbantuan AI (*human-in-the-loop*).

---

## Fitur Utama

1. **Optimasi Menu Berbasis Resep & Verifikasi Independen (MILP PuLP/CBC):**
   - Menyusun jadwal menu multi-hari (`staple`, `protein`, `vegetable`, `fruit`) hanya dari varian resep berstatus `reviewed` sambil menegakkan kendala keras anggaran, kecukupan nutrisi (berbasis BDD dan retensi gizi), alergen, pengulangan keluarga menu, dan batas stok bersih.
   - Setiap solusi diverifikasi ulang secara independen dari data mentah oleh `optimizer/verifier.py`; skenario yang tidak memenuhi seluruh kendala dilaporkan jujur sebagai `INFEASIBLE` tanpa rekomendasi menu buatan.

2. **Fondasi Kualitas Inventaris, Lot Batch & Referensi Pasar Indonesia:**
   - Memisahkan `recorded_raw_g` vs `usable_raw_g` secara sadar tanggal produksi (`expires_at`, kerusakan, reservasi aktif, selisih fisik, pengiriman `PARTIAL`/`DELAYED`).
   - Memisahkan tabel referensi harga pasar pangan Indonesia (`market_price_references`) dari harga pemasok nyata (`ingredient_prices`) dengan pelacakan `price_provenance`.

3. **Penahanan Keamanan Bahan Bermasalah (`SAFETY HOLD`) & Anti-Bypass:**
   - Pelaporan insiden multi-lot/multi-bahan (`SPOILAGE`, `SUSPECTED_CONTAMINATION`, `ABNORMAL_ODOR_APPEARANCE`, dll.) langsung mengisolasi lot terdampak (`ON_HOLD` / `REJECTED_DISPOSED`) di `compute_usable_inventory` tanpa menahan lot bersih terpisah.
   - Otomatis membekukan rencana operasional aktif yang memakai bahan tersebut (`ON_HOLD`), menelusuri potensi paparan produksi (`PRODUCTION_CONSUMPTION`, reservasi, batch masakan), serta menolak pelepasan sepihak internal (`POST /api/v1/incidents/{id}/release-hold` → `403 Forbidden`) maupun *stock override* (`409 Conflict`).

4. **Pemulihan Pengadaan Adaptif (`MIN_DISRUPTION` vs `MIN_COST`):**
   - Formulasi leksikografis 2-tahap meminimalkan jumlah pergantian slot menu ($D_{\min}$) terlebih dahulu, lalu meminimalkan total biaya pengadaan pada kondisi stok lot bersih & harga terbaru.
   - Menyajikan perbandingan kontrafaktual 4-arah yang adil tanpa klaim penghematan palsu, delta pengadaan ekspor CSV aman formula, dan *stale inventory snapshot guard* (`409 Conflict`).

5. **Siklus Hidup Rencana Operasional & Pemeriksaan Menu AI (`QC`):**
   - Memisahkan riwayat persetujuan historis (`MenuReviewRecord`) dari penugasan operasional efektif (`operational_plan_assignments`: `ACTIVE`, `ON_HOLD`, `SUPERSEDED`, `APPROVED_NOT_ACTIVE`) dengan aktivasi eksplisit oleh `KITCHEN_MANAGER` dan pemblokiran pemeriksaan QC baru atas rencana `ON_HOLD`/`SUPERSEDED`.
   - Autentikasi sesi cookie `HttpOnly` + CSRF (`Argon2id`), RBAC backend (`KITCHEN_MANAGER`, `MENU_PLANNER`, `QC_OFFICER`), isolasi antar-dapur, penghapusan metadata EXIF pada unggahan foto, serta adaptor Vision QC (`deterministic_test` / OpenAI / Gemini) dengan konfirmasi wajib Petugas QC.

---

## Struktur Repositori

```text
.
├── apps/
│   └── web/                  # Frontend Next.js 15 App Router + React 19 + Tailwind CSS v4
├── services/
│   └── api/                  # Backend FastAPI + SQLAlchemy 2 + Alembic + PuLP/CBC MILP
│       ├── alembic/          # Migrasi skema hingga 0006_sprint3b1_3c_ops_incidents
│       ├── app/
│       │   ├── api/routes/   # Endpoint REST v1 (/auth, /datasets, /scenarios, /recovery, /incidents, /operational-plans, /qc, /dashboard)
│       │   ├── data/         # Fixture deterministik DEMO_ONLY (termasuk Recovery 3B & Triple Incident 3C)
│       │   ├── db/           # Model ORM & SQLiteVaultRepository
│       │   ├── incidents/    # Layanan penahanan keamanan & paparan produksi
│       │   ├── inventory/    # Normalisasi satuan, mapping bahan & usable inventory
│       │   ├── operations/   # Mesin siklus hidup rencana operasional
│       │   ├── optimizer/    # MILP model builder, solver CBC, verifier independen & diagnostik
│       │   ├── recovery/     # Mesin optimasi minimum-disruption & delta belanja
│       │   ├── reviews/      # Alur peninjauan rencana & snapshot guard
│       │   └── vision/       # Keamanan foto QC & adaptor Vision AI
│       ├── scripts/          # CLI manajemen dapur/user & seed akun demo
│       └── tests/            # Suite pengujian otomatis pytest (82 test)
├── datasets/                 # Artefak dataset pendukung
└── qa/                       # Bukti QA, screenshot lintas viewport & evaluasi vision held-out
```

---

## Cara Menjalankan Secara Lokal

### 1. Prasyarat
- Python 3.11+ & `pip`
- Node.js 20+ & `npm`

### 2. Backend (`services/api`)

```powershell
cd services/api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts/seed_demo_users.py

# Mode uji deterministik untuk demonstrasi lokal tanpa API key Vision eksternal
$env:GIZIOPTIMA_VISION_PROVIDER="deterministic_test"
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

Dokumentasi OpenAPI tersedia di `http://127.0.0.1:8000/docs`.

### 3. Frontend (`apps/web`)

```powershell
cd apps/web
copy .env.example .env.local
npm install
npm run build
npm run start
```

Buka `http://127.0.0.1:3000` di browser.

---

## Verifikasi Pengujian

- **Backend (`services/api`):**
  ```powershell
  .\.venv\Scripts\pytest.exe -q
  ```
  Tercatat **82 passed, 0 failed** (termasuk roundtrip migrasi Alembic `0006`, uji balapan aktivasi paralel, integrasi pemulihan minimum-disruption, insiden safety hold 3 bahan, penghapusan EXIF, RBAC/isolasi dapur, dan persistensi lintas proses).

- **Frontend (`apps/web`):**
  ```powershell
  npm run typecheck
  npm test
  npm run build
  ```
  Tercatat **0 error TypeScript**, **6 test files / 21 Vitest passed**, serta **13/13 rute `next build`** terkompilasi bersih dan teruji responsif tanpa horizontal overflow pada lebar `320 px` s.d. `1440 px`.
