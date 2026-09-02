# BoundRelay

> TypeScript, Python ve Go üzerinde sınırlandırılmış, gözlemlenebilir agent orkestrasyonunu temelden öğren ve geliştir.

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

İlk çalıştırılabilir milestone olan **M0**, tek bir destek talebi yönlendirme senaryosunu TypeScript ve Python ile offline çalıştıracak, ortak JSONL trace üretecek ve parity kontrolünden geçirecektir. Gerçek LLM veya API anahtarı gerektirmeyecektir.

Detaylar için [foundation design](docs/design/2026-09-02-foundation-design.md) ve [roadmap](ROADMAP.md) dosyalarına bakın.
