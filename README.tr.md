# BoundRelay

> TypeScript, Python ve Go üzerinde sınırlandırılmış, gözlemlenebilir agent orkestrasyonunu temelden öğren ve geliştir.

## Proje durumu

**Aşama:** M0 behavioral parity vertical slice tamamlandı.

M0; canonical support-triage senaryosu ve sözleşmeleri, offline deterministic/scripted-model routing, TypeScript ve Python implementasyonları, şemaya uygun JSONL trace’ler, invalid-route için fail-closed davranış ve normalize edilmiş diller arası parity doğrulaması sunuyor. Belgelenmiş yerel gate, evidence’i checkout edilen Git revision’ına bağlar; GitHub Actions aynı gate’i Node.js 24 ve Python 3.14 üzerinde çalıştırır ve `.boundrelay/m0/` çıktısını `m0-verification-<revision>` adıyla yükler.

## M0'ı yerelde doğrulama

Gereksinimler: Node.js 24 ve Python 3.14. Repository kökünde:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e lessons/00-workflow-or-agent/python
npm ci --prefix lessons/00-workflow-or-agent/typescript
python scripts/verify_m0.py
```

Bu komut contract testlerini, iki dilin testlerini, verification-safety testlerini ve yedi parity kombinasyonunu çalıştırır. İstenen case/mode bağını, result–trace `run_id` tutarlılığını, terminal event–status eşleşmesini, specialist dispatch sınırlarını ve evidence metadata’sını doğrular. Evidence `HEAD` revision’ına bağlandığı için certification gate temiz bir Git worktree gerektirir; aday değişiklikleri commit ettikten sonra çalıştırın. Komut ilk kontrolden önce eski M0 evidence dizinini kaldırır; dolayısıyla başarısız bir yeniden çalıştırma önceki `PASSED` kaydını bırakamaz. Ayrıntılı anlatım için [Ders 00](lessons/00-workflow-or-agent/README.md) dosyasına bakın.

## Proje kimliği

**BoundRelay** şemsiye proje adıdır; ilk repository slug’ı `boundrelay` olacaktır. İsim iki temel ilkeyi birleştirir:

- **Bound:** açık sözleşmeler, bütçeler, yetkiler, durma koşulları ve hata sınırları;
- **Relay:** routing, delegation, handoff, fan-out/fan-in ve diller arası koordinasyon.

İlk aşamada tek ve odaklı bir repository bulunacaktır. **BoundRelay Learn**, **BoundRelay Protocol**, **BoundRelay Runtime**, **BoundRelay CLI** ve **BoundRelay Inspector** adları gelecekte gerçekten bağımsız çıktılar oluşursa kullanılabilecek ürün ailesi adlarıdır; başlangıçta ayrı projeler oluşturulmayacaktır.

## Projenin amacı

Bu proje yalnızca “birden fazla agent nasıl çalıştırılır?” sorusunu yanıtlamaz. Daha önemli olan şu kararları öğretir:

- Bu problem için gerçekten agent gerekiyor mu?
- Bilinen adımlar normal kodla mı yürütülmeli?
- LLM hangi dar ve belirsiz kararı vermeli?
- State, handoff, retry, timeout, approval ve budget nasıl sınırlandırılmalı?
- Bir çalışmanın başarılı olduğu hangi evidence ile kanıtlanmalı?
- Aynı davranış farklı dillerde nasıl korunmalı?

## Öğretim yöntemi

Her ders aynı sırayı izler:

1. Problem ve başarı ölçütü.
2. Deterministic baseline.
3. En küçük agentic ekleme.
4. Naif ama çalışır görünen sürüm.
5. Kontrollü hata enjeksiyonu.
6. Sözleşmeler ve güvenlik sınırlarıyla düzeltilmiş sürüm.
7. Ortak invariant ve trace doğrulaması.
8. “Bu çözümü ne zaman kullanmamalısın?” bölümü.

## Dil yaklaşımı

TypeScript, Python veya Go kaynak gerçek değildir. Kaynak gerçek şunlardır:

- senaryo tanımı;
- input/output şemaları;
- gözlemlenebilir event sözleşmesi;
- golden fixture’lar;
- hata senaryoları;
- doğrulama invariant’ları.

Dil implementasyonları aynı davranışı korur fakat kendi ekosistemlerine uygun, idiomatic biçimde yazılır.

## İlk teslimat

İlk çalıştırılabilir milestone olan **M0**, tek bir destek talebi yönlendirme senaryosunu TypeScript ve Python ile offline çalıştırır, ortak JSONL trace üretir ve parity kontrolünden geçirir. Gerçek LLM veya API anahtarı gerektirmez.

Detaylar için [foundation design](docs/design/2026-09-02-foundation-design.md) ve [roadmap](ROADMAP.md) dosyalarına bakın.
