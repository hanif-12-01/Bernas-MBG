# GiziOptima Adaptive Procurement — Persistent Backend (Sprint 2A)

> **Peringatan Penting:** Seluruh dataset bawaan (`DEMO_ONLY`, `simulation_only=true`) bersifat **SINTETIS** untuk demonstrasi teknis dan belum melalui validasi ahli gizi atau pengesahan standar BGN.

## Struktur Direktori

```text
services/api/
  alembic.ini
  alembic/
    env.py
    versions/0001_initial_schema.py
  app/
    main.py
    db/
      models.py                 # 16 tabel SQLAlchemy 2 (FK, Unique, Check, Index)
      session.py                # Engine SQLite (PRAGMA foreign_keys=ON, WAL), Alembic runner & seed
      repository.py             # Transactional SQLiteVaultRepository
    api/routes/
      health.py                 # GET /api/v1/health
      datasets.py               # POST /datasets/import, GET /datasets/{id}, /ingredients, /recipes
      scenarios.py              # Scenarios CRUD/clone/overrides, /optimize, /runs/{id}, /shopping-list, /export.csv
      comparisons.py            # GET /api/v1/comparisons?base_id=&candidate_id=
    ingestion/
      unit_converter.py         # Decimal exact IDR/kg -> IDR/g, finite checks
      csv_parser.py             # Validasi 4 CSV multipart + atomic immutable DatasetVersion
    analytics/
      comparison.py             # Perbandingan run + margin gizi + kompatibilitas input
    export/
      csv_exporter.py           # Formula-safe CSV export + banner simulation_only
    domain/
      models/schemas.py
      recipe_calculator.py
    optimizer/
      model_builder.py
      solver.py
      verifier.py
      diagnostics.py
    data/
      synthetic_fixture.py
  tests/
    conftest.py
    test_unit_and_calculator.py
    test_optimizer_and_api.py
    test_audit_and_mutations.py
    test_exhaustive_optimality.py
    test_sprint2a_persistence_and_api.py
  requirements.txt
  README.md
```

## Instalasi & Migrasi Database

```powershell
cd "d:\LOMBA\AI Builder Challenge 2026\services\api"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\alembic.exe upgrade head
```

Atur URL database opsional melalui environment variable `GIZIOPTIMA_DATABASE_URL` (default: `sqlite:///./gizioptima.db`).

## Menjalankan Backend

```powershell
cd "d:\LOMBA\AI Builder Challenge 2026\services\api"
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

OpenAPI docs tersedia di `http://127.0.0.1:8000/docs`.

## Menjalankan Seluruh Test (`pytest`)

```powershell
cd "d:\LOMBA\AI Builder Challenge 2026\services\api"
.\.venv\Scripts\pytest.exe -v
```

## Pengelolaan pengguna dan dapur

Jalankan perintah berikut dari `services/api` sebagai operator yang memiliki akses
shell dan akses tulis ke database backend. CLI menggunakan
`GIZIOPTIMA_DATABASE_URL` atau database SQLite lokal yang sama dengan layanan.
Untuk pembuatan akun dan reset sandi, CLI meminta sandi secara interaktif tanpa
menampilkannya. Otomasi yang sudah memiliki akses ke penyimpanan rahasia dapat
mengirim sandi melalui stdin dengan `--password-stdin`.

```powershell
.\.venv\Scripts\python.exe scripts/manage_access.py create-kitchen --code DAPUR-01 --name "Dapur 01" --region Bandung
.\.venv\Scripts\python.exe scripts/manage_access.py create-user perencana01 --email perencana01@example.org --name "Perencana 01" --kitchen DAPUR-01 --role MENU_PLANNER
.\.venv\Scripts\python.exe scripts/manage_access.py set-membership perencana01 --kitchen DAPUR-01 --role QC_OFFICER
.\.venv\Scripts\python.exe scripts/manage_access.py reset-password perencana01
.\.venv\Scripts\python.exe scripts/manage_access.py remove-membership perencana01 --kitchen DAPUR-01
.\.venv\Scripts\python.exe scripts/manage_access.py disable-user perencana01
.\.venv\Scripts\python.exe scripts/manage_access.py enable-user perencana01
```

`set-membership --default` memilih dapur untuk sesi masuk berikutnya. Pengubahan
peran dan pencabutan keanggotaan mengakhiri sesi di dapur terkait. Reset sandi dan
penonaktifan akun mengakhiri seluruh sesi akun tersebut. Perubahan dicatat di
`audit_events` dengan identitas operator shell sebagai metadata. Simpan akses
shell dan database untuk operator berwenang.

## Dataset dan migrasi

Impor CSV menambah versi privat pada dapur pengimpor. Pilih ID versi tersebut
saat membuat skenario untuk menjadikannya sumber data optimasi. Katalog demo
bawaan tetap tersedia sebagai versi simulasi bersama. Impor bukan persetujuan
ahli gizi dan hasil optimasi tetap ditandai sebagai simulasi.

Migrasi `0003_dataset_kitchen_scope` menautkan impor lama ke dapur ketika rekam
audit memiliki satu dapur yang dapat diidentifikasi. Impor yang pemiliknya tidak
dapat ditentukan tetap tersimpan tetapi tidak tersedia melalui aplikasi.
Operator dapat mengimpor ulang dari sumber yang diketahui pada dapur yang tepat.

Sebelum upgrade, buat backup konsisten dengan SQLite backup API atau dengan
menghentikan penulis database dan menyelesaikan checkpoint WAL. Backup juga
direktori foto QC privat dengan tujuan penyimpanan berakses terbatas. Uji
pemulihan pada salinan sebelum migrasi basis data aktif. Perintah di bawah
menerapkan migrasi ke database yang dikonfigurasi pada environment backend.

```powershell
.\.venv\Scripts\python.exe -c "from app.db.session import run_alembic_migrations; run_alembic_migrations()"
```

## Konfigurasi pengoperasian

- Atur `GIZIOPTIMA_ENV=production` untuk cookie sesi `Secure` dan menonaktifkan
  pembuatan akun demo. Jalankan situs melalui HTTPS dengan proxy tepercaya.
  Batasi asal di `GIZIOPTIMA_CORS_ORIGINS` ke origin frontend yang digunakan.
- Login memakai pembatas percobaan per alamat peer dan per pasangan
  peer/identitas, beserta batas verifikasi Argon2 yang berjalan bersamaan. Batas
  di aplikasi berlaku per proses. Untuk beberapa worker, terapkan pembatas
  bersama di depan layanan dan percaya forwarded header hanya dari proxy yang
  dikonfigurasi.
- Simpan rahasia provider pada backend. API membatasi satu foto QC hingga 5 MiB
  dan setiap CSV hingga 2 MiB. Pasang juga batas ukuran request di proxy untuk
  menghentikan unggahan besar sejak awal. Uji konfigurasi TLS dan pemulihan
  backup sebelum menempatkan layanan di jaringan publik.
  Pengaturan Vision dan kebijakan foto QC ada di [VISION_QC.md](VISION_QC.md).
