# BoundRelay

> TypeScript, Python ve Go üzerinde sınırlandırılmış, gözlemlenebilir agent orkestrasyonunu temelden öğren ve geliştir.

## Proje durumu

**Aşama:** v1.0 takibi (P1–P5) sertifikalı M0–M8 üzerine uygulandı; mevcut revision'ı `python scripts/verify_m8.py` ile (M8→M0 zinciri) doğrulayın. P5 mapping suite'leri için [mappings/README.md](mappings/README.md) ve `.github/workflows/p5.yml` dosyasına bakın.

M2, TypeScript ve Python'da offline support-router → deterministik specialist handoff ekler. Route kararı doğrulandıktan sonra sabit `0.80` güven eşiği uygulanır; sender intent, alıcının yalnızca `ticket_id + request_text` içeren girdisinden ayrı tutulur. Beş canonical senaryo code/model routing, düşük güven fallback, context loss ve erişilemeyen alıcıyı kapsar. Başarıda tam bir alıcı çağrılır; rejection durumunda çağrı ve retry yapılmaz. M2 doğrulaması M1'i alt milestone authority olarak korur.

M3, üç bağımsız offline order-brief worker'ı, sıralı limit 1 / paralel limit 2, typed partial/all-failed sonuçları, tam canonical fan-in ve tek deterministic synthesizer ekler. M4, typed run-state dokümanı, write-ahead atomic checkpoint'ler, fail-closed resume/replay ve deterministik cancellation ekler; kaydedilen sonuçlar asla yeniden çalıştırılmaz. M5, projenin ilk mutating işlemi olan `order-closure`'u ekler: payload-digest'e bağlı approval, dosya destekli ledger ile anahtar-başına-once idempotency, append-only audit ve dış gerçeklik kanıtlanamadığında `UNKNOWN`.

M6, her dersin çalışma sonuçlarına deterministik attribution (saat-enjeksiyonlu gecikme, fixture-fiyatlı maliyet, çok-fazlı deneme uzlaştırması), 38 canonical case için dil-bağımsız golden trajectory'ler, bağımsız fail-closed regression evaluator `tools/evaluate.py`, makine-okur failure matrix `fixtures/failure-matrix.yaml` (21 hata sınıfı) ve bildirilen tüm hataları canlı replay eden `tools/chaos.py` ekler.

M7, D-003 gereği Go'yu üçüncü dil olarak ekler: `go/` altında sıfır-bağımlılık (yalnızca stdlib) Go modülü, strict JSON decoding, sentinel failure kodları, `context.Context` fatal-drain ve sınırlı semaphore admission ile. M7 zamanında 13 M0/M3 anahtarı üç-dilli golden parity'ye ulaştı; D-018'in ertelediği M1/M2/M4/M5 Go port'ları v1.0 takibi P4 olarak geldi ([D-020](docs/decisions/D-020-v1-track-go-parity-and-mapping-set.md)) ve M7 authority'si 38 anahtarın tamamını kapsayacak şekilde genişledi.

M8, D-008 gereği ilk framework mapping'ini ekler: `mappings/langgraph-m3/` altında LangGraph `1.2.20` (exact pin) ile M3 `order-brief` yeniden inşası; altı case için business-result parity, fail-closed dependency isolation ve D-008'in dört sorusu (provided / retained / hidden / exit) kanıtlanabilir cevaplarla.

v1.0 takibi beş sıralı paket halinde teslim edildi (PR #32–#42): P1 production checklist + executable linkage test, P2 trace inspector, P3 fault-injection labs, P4 kalan Go port'ları (M1/M2/M4/M5), P5 framework mapping seti (OpenAI Agents SDK×M1, Google ADK×M2, Mastra×M3 (TS), Eino×M3 (Go)). Milestone'ların tamamlanmış doğrulama bölümleri için İngilizce [README](README.md)'ye bakın.

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

## M2'yi yerelde doğrulama

Yukarıdaki M0 ve M1 kurulumlarından sonra Ders 02'yi kurun:

```bash
python -m pip install -e lessons/02-routing-handoff/python
npm ci --prefix lessons/02-routing-handoff/typescript
python scripts/verify_m2.py
```

Kapı temiz Git worktree gerektirir, M1 üzerinden M0'ı da çalıştırır, iki M2 implementasyonunu ve beş CLI senaryosunun parity'sini doğrular. `HEAD` değişmemişse kanıt `.boundrelay/m2/verification-evidence.json` dosyasına yazılır. GitHub Actions aynı komutu çalıştırır ve `m2-verification-<revision>` artifact'ını yükler. Kurulum, event akışı, hata davranışı ve alıştırmalar için [Ders 02](lessons/02-routing-handoff/README.md). Alıcılar deterministik ve read-only kalır; gerçek provider, retry, persistence, side effect, Go, paralellik ve framework adapter kapsam dışındadır.

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
