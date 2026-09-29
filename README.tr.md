# BoundRelay

> TypeScript, Python ve Go üzerinde sınırlandırılmış, gözlemlenebilir agent orkestrasyonunu temelden öğren ve geliştir.

## Proje durumu

**Aşama:** M1 bounded single-agent tool loop tamamlandı.

M0, deterministic-vs-model routing baseline'ı olarak korunuyor. M1 ise canonical `order-investigation` senaryosu için offline, deterministic ve read-only tek-agent tool loop ekliyor: direct function-call baseline, bounded model–tool–observation döngüsü, iki typed read-only tool, hard model-step/token budget, fail-closed validation, açık timeout/execution failure davranışı, strict JSONL trace ve TypeScript/Python behavioral parity.

M1 certification gate önce mevcut M0 authority'yi çalıştırır, ardından sekiz M1 canonical case'i iki dilde doğrular. Başarılı evidence exact Git revision'ına bağlanır ve `.boundrelay/m1/` altında yazılır; GitHub Actions aynı authority command'ı Node.js 24 ve Python 3.14 üzerinde çalıştırıp `m1-verification-<revision>` artifact'ını yükler.

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

M0 gate contract testlerini, iki dilin testlerini, verification-safety testlerini ve yedi parity kombinasyonunu çalıştırır. Evidence `HEAD` revision'ına bağlı olduğu için temiz Git worktree gerekir. Ayrıntılar için [Ders 00](lessons/00-workflow-or-agent/README.md).

## M1'i yerelde doğrulama

M1, M0'ı regression authority olarak koruduğu için iki lesson runtime'ını da kurun:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e lessons/00-workflow-or-agent/python
python -m pip install -e lessons/01-bounded-tool-loop/python
npm ci --prefix lessons/00-workflow-or-agent/typescript
npm ci --prefix lessons/01-bounded-tool-loop/typescript
python scripts/verify_m1.py
```

M1 gate önce eski M1 evidence'ini temizler, M0 authority'yi çalıştırır, M1 contract ve iki dil testlerini doğrular, verifier-safety testlerini yürütür, sekiz canonical case'i iki CLI üzerinden çalıştırır ve normalize edilmiş result/trace eşitliğini kontrol eder. Başarılı çalışmada revision-bound evidence `.boundrelay/m1/verification-evidence.json` dosyasına yazılır.

M1 bilinçli olarak offline ve read-only kalır. Real model provider, retry, mutating tool, persistence, approval/idempotency, Go parity, MCP/framework adapter veya ortak general-purpose runtime eklemez. Ayrıntılar için [Ders 01](lessons/01-bounded-tool-loop/README.md).

## Proje kimliği

**BoundRelay** şemsiye proje adıdır; ilk repository slug'ı `boundrelay` olacaktır. İsim iki temel ilkeyi birleştirir:

- **Bound:** açık sözleşmeler, bütçeler, yetkiler, durma koşulları ve hata sınırları;
- **Relay:** routing, delegation, handoff, fan-out/fan-in ve diller arası koordinasyon.

İlk aşamada tek ve odaklı bir repository bulunacaktır. **BoundRelay Learn**, **BoundRelay Protocol**, **BoundRelay Runtime**, **BoundRelay CLI** ve **BoundRelay Inspector** adları gelecekte gerçekten bağımsız çıktılar oluşursa kullanılabilecek ürün ailesi adlarıdır; başlangıçta ayrı projeler oluşturulmayacaktır.

## Projenin amacı

Bu proje yalnızca "birden fazla agent nasıl çalıştırılır?" sorusunu yanıtlamaz. Daha önemli olan şu kararları öğretir:

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
8. "Bu çözümü ne zaman kullanmamalısın?" bölümü.

## Dil yaklaşımı

TypeScript, Python veya Go kaynak gerçek değildir. Kaynak gerçek şunlardır:

- senaryo tanımı;
- input/output şemaları;
- gözlemlenebilir event sözleşmesi;
- golden fixture'lar;
- hata senaryoları;
- doğrulama invariant'ları.

Dil implementasyonları aynı davranışı korur fakat kendi ekosistemlerine uygun, idiomatic biçimde yazılır.

## İlk teslimat

M0 deterministic-vs-model routing kararını öğretir. M1 bunun üzerine bounded, read-only tek-agent tool loop ekler. Her iki milestone da TypeScript/Python parity ve revision-bound verification ile korunur; gerçek LLM/API anahtarı gerekmez.

Detaylar için [foundation design](docs/design/2026-09-02-foundation-design.md) ve [roadmap](ROADMAP.md) dosyalarına bakın.
