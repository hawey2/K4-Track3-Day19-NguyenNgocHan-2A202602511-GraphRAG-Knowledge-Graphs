# Báo cáo Day 19 — Flat RAG vs GraphRAG

**Họ tên:** Nguyễn Ngọc Hân  **MSSV:** 2A202602511  **Ngày:** 5/10/2026

> Kỳ vọng và thang điểm: `SUBMISSION.md`. Mọi số liệu khớp với `ket_qua_benchmark_kg.txt`. Bản thiết kế ontology nộp riêng ở `report/ONTOLOGY.md`.
>
> **Môi trường chạy:** Docker không có sẵn → dùng Neo4j Community 5.26 chạy trực tiếp bằng Java (`/tmp/neo4j-community-5.26.0`). Provider: **OpenAI `gpt-4o-mini`** (chat) + **`text-embedding-3-small`** (embedding). Graph: **206 node / 386 cạnh**, 176 chunk.

## 1. Chi phí (10 điểm)

Hai bảng từ `ket_qua_benchmark_kg.txt`:

```
== Indexing (one-off)
pipeline  calls    in_tok  out_tok       USD  seconds
flat        176     56072        0   0.00112     62.7
graph       196     91958     4932   0.00946    130.6

== Querying (mean per question)
pipeline  recall  judge   in_tok  out_tok       USD  seconds
flat        0.43   1.00      694       48   0.00013     1.48
graph       0.69   1.50     3051       85   0.00050     2.22
```

| Chỉ số | Flat | Graph | Graph / Flat |
| --- | --- | --- | --- |
| Indexing USD | 0.00112 | 0.00946 | **×8.45** |
| Indexing giây | 62.7 | 130.6 | **×2.08** |
| Mỗi câu: USD | 0.00013 | 0.00050 | **×3.85** |
| Mỗi câu: giây | 1.48 | 2.22 | **×1.50** |
| Mỗi câu: in_tok | 694 | 3051 | **×4.40** |

**Chi phí tăng thêm đến từ đâu?**
> **Indexing:** `flat` chỉ embed 176 chunk (176 lần gọi, 56.072 in_tok). `graph` = 176 embed **+ 20 lần gọi chat** trích xuất tin (mỗi bài 1 lần), nên `calls` chỉ tăng 20 nhưng `in_tok` tăng 35.886 và `out_tok` từ 0 lên 4.932; phần chênh USD `0.00946 − 0.00112 = 0.00834` gần như **toàn bộ nằm ở bước trích tin bằng LLM** (luật dùng regex nên 0 token chat). Nói cách khác, chi phí dựng graph tỉ lệ với **số bài báo**, không phải số Điều luật.
> **Mỗi câu hỏi:** `in_tok` graph gấp **4,40 lần** flat (3.051 vs 694) vì `GRAPH_PROMPT` chèn thêm khối "Dữ kiện knowledge graph" (nhiều fact khoản luật, có khi cả văn bản khoản dài). Cùng model `gpt-4o-mini` nên USD/câu gấp ~3,85 lần, thời gian gấp ~1,5 lần. Đây thuần là **prompt dài hơn**, không phải gọi LLM nhiều lần hơn.
> **Điểm hòa vốn:** `Q* = (graph_index − flat_index) / (graph_q − flat_q) = 0.00834 / (0.00050 − 0.00013) = 0.00834 / 0.00037 ≈ 22,5`. Tức phải hỏi **~23 câu** thì tiền dựng graph mới được khấu hao hết; benchmark chỉ có 6 câu nên GraphRAG đắt hơn Flat về tổng USD. Nhưng lợi ích không nằm ở USD mà ở `judge` (1,50 vs 1,00) — xem mục 2, 4.

## 2. Từng câu hỏi (10 điểm)

| Câu | Loại | Flat recall / judge | Graph recall / judge | Thắng | Vì sao (1 câu) |
| --- | --- | --- | --- | --- | --- |
| Q1 | single-hop-law | 1.00 / 2 | 1.00 / 2 | Hòa | Định nghĩa "tiền chất" nằm gọn trong khoản 4 Điều 2 Luật PCMT; Flat đã lấy đủ, graph chỉ thêm số Điều. |
| Q2 | single-hop-news | 1.00 / 2 | 1.00 / 2 | Hòa | Tên + án tử hình nằm gọn trong 1 bài (36kg); Flat đủ. |
| Q3 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | Flat "Không đủ thông tin" (án ở tin, Điều 251 + khung ở luật); graph nối `Person→Case→Crime→Article→Clause` ra đủ 36 tháng + Điều 251 + `02–07 năm`. |
| Q4 | cross-kb | 0.00 / 0 | 0.33 / 1 | **Graph** (nhưng hụt) | Flat "Không đủ thông tin"; graph nêu đúng tội nhưng **không có khung tối đa** vì `context()` bỏ khoản 4 Điều 255 (xem E2). |
| Q5 | cross-kb-multi-hop | 0.60 / 1 | 0.80 / 1 | **Graph** (nhưng sai Điều) | Cả hai nêu tội + MDMA + `khoản 4` + `tử hình`; graph **sai số Điều (251 thay vì 250)** vì context trộn khoản của 4 Điều (xem E5). |
| Q6 | aggregation | 0.00 / 1 | 0.00 / 1 | Hòa (đều 0 recall) | Cả hai liệt kê đúng 3 vụ MDMA nhưng **không dùng đúng tên** trong `must_include` (xem E4). |

**Quy luật loại câu → bên thắng:** đáp án nằm gọn trong **một** tài liệu (Q1, Q2) thì Flat RAG đủ và rẻ hơn — GraphRAG chỉ tốn thêm token. GraphRAG thắng khi phải **ghép hai KB** (Q3–Q5). Hai ngoại lệ đáng chú ý: (1) câu hỏi về **khung tối đa** ở tội định khung theo tình tiết định tính, không theo khối lượng chất (Điều 255) → ontology thiếu cấu trúc "khoản nặng nhất" nên GraphRAG hụt (E2); (2) câu **aggregation** (Q6) có `judge=1` cho cả hai nhưng `recall=0` — phép đo từ khóa phạt oan câu trả lời đúng (E4). Vì vậy bảng `judge` trung bình (flat 1,00 vs graph 1,50) là chỉ số phản ánh lợi ích GraphRAG trung thực hơn `recall` (0,43 vs 0,69).

## 3. Phân tích lỗi (20 điểm)

### Lỗi E2: Thiếu ngữ cảnh luật — bộ lọc khoản bỏ mất khoản nặng nhất (lỗi ở bước thiết kế ontology + KG-3)

- **Hiện tượng:** câu hỏi về **mức phạt tù tối đa** (Q4) không được trả lời dù graph có đủ Điều 255 với khoản 4 ghi "tù 20 năm hoặc tù chung thân". Câu trả lời GraphRAG tự nhận không đủ thông tin.

- **Bằng chứng (trích từ `ket_qua_benchmark_kg.txt`, Q4 pipeline `graph`, judge=1):**
  ```
  Giang hồ 'Hoàng Nato' bị bắt về hành vi tổ chức sử dụng trái phép chất ma túy.
  Tuy nhiên, trong ngữ cảnh không có thông tin cụ thể về mức án phạt tù tối đa cho hành vi này
  theo Bộ luật Hình sự. Do đó, không đủ thông tin để trả lời câu hỏi về mức phạt tù tối đa.
  ```
  `recall=0,33` (chỉ khớp `tổ chức sử dụng`); thiếu `chung thân` → trong khi gold là "khung cao nhất là tù 20 năm hoặc tù chung thân".

  Kiểm chứng trực tiếp trên graph đã dựng (`MATCH (a:Article {id:'Điều 255 BLHS'})-[:HAS_CLAUSE]->(cl:Clause) OPTIONAL MATCH (cl)-[:MENTIONS]->(s:Substance) RETURN cl.number, cl.penalty, collect(s.name)`):
  ```
  khoản 1: phạt tù từ 02 năm đến 07 năm        | chat: []
  khoản 2: phạt tù từ 07 năm đến 15 năm        | chat: []
  khoản 3: phạt tù từ 15 năm đến 20 năm        | chat: []
  khoản 4: phạt tù 20 năm hoặc tù chung thân   | chat: []   <-- khung tối đa, KHÔNG nhắc chất nào
  khoản 5: phạt tiền ...                        | chat: []
  ```
  Và `context()` cho câu Q4 thực tế chỉ trả về **khoản 1** của Điều 255:
  ```
  [Điều 255 BLHS - Tội tổ chức sử dụng trái phép chất ma túy] khoản 1: ... bị phạt tù từ 02 năm đến 07 năm.
  ```

- **Nguyên nhân:** bộ lọc khoản trong `Neo4jGraph.context` (`src/graph.py:279-280`) chỉ giữ `cl.number = 1` **hoặc** khoản `MENTIONS` một `Substance` mà vụ `INVOLVES`. Vụ "Hoàng Nato" chỉ có chất `etomidate` — **không nằm trong danh sách `SUBSTANCES`** (đồng thời là E3) → không khớp `MENTIONS` nào. Điều 255 lại định khung theo **tình tiết định tính** ("có tổ chức", "tái phạm nguy hiểm"), không theo khối lượng chất, nên mọi khoản đều không nhắc chất. Gốc rễ là **thiết kế ontology gợi ý** không mô hình hóa quan hệ "khoản nặng nhất" / ngưỡng khối lượng — đúng điểm yếu LAB_GUIDE Bước 2 đã cảnh báo. Đây là lỗi **chọn khoản**, không phải LLM.

- **Đề xuất sửa:** trong `context()`, với mỗi Điều luật lấy **khoản 1 + khoản số lớn nhất + các khoản MENTIONS chất của vụ**:
  ```cypher
  MATCH (k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)
  WHERE elementId(k) IN $ids
  WITH a, cl,
       cl.number = 1 AS is_base,
       EXISTS { MATCH (k)-[:INVOLVES]->(s:Substance)<-[:MENTIONS]-(cl) } AS is_relevant,
       max(cl.number) OVER (PARTITION BY a) AS max_n
  WHERE is_base OR is_relevant OR cl.number = max_n
  RETURN ...
  ```
  Đánh đổi: prompt dài thêm 1–3 khoản mỗi Điều (tăng `in_tok`/câu, đã gấp 4,4×) và có thể gây nhiễu khi LLM tự chọn khoản sai; bù lại không bỏ sót khung tối đa. Phương án khác: dựng property `is_max_penalty` cho `Clause` lúc build (truy vấn rẻ, nhưng cần logic so sánh mức án).

---

### Lỗi E4: Phép đo sai — `recall=0,00` nhưng `judge=1` cho cùng một câu trả lời (lỗi ở khâu đánh giá)

- **Hiện tượng:** ở Q6, **cả hai** pipeline có `recall=0,00` nhưng `judge=1`. Câu trả lời liệt kê đúng 3 vụ MDMA nhưng dùng **tên mô tả** thay vì đúng chuỗi từ khóa trong `must_include` (`Cái Quang Huy`, `Lê Minh Thành`, `Pháp y tâm thần`), nên `keyword_recall` (so khớp chuỗi con) cho 0.

- **Bằng chứng (trích `ket_qua_benchmark_kg.txt`, Q6):**

  Pipeline `graph` (`recall=0.00 judge=1`):
  ```
  1. **Vụ vận chuyển ma túy từ Đức về Việt Nam**: Liên quan đến tổng khối lượng hơn 9,6kg MDMA.
  2. **Vụ góp tiền mua ma túy tại Hà Nội**: Có liên quan đến 5 viên MDMA.
  3. **Vụ tổ chức sử dụng ma túy tại Sầm Sơn**: Có liên quan đến 0,686g MDMA.
  ```
  Pipeline `flat` (`recall=0.00 judge=1`) cũng đúng về nội dung nhưng gọi tên bằng "Đức / Thành / Đông".

  Đối chiếu `must_include` trong `data/benchmark_kg.json`:
  ```
  Q6 must_include: ["Cái Quang Huy", "Lê Minh Thành", "Pháp y tâm thần"]
  ```
  Cả hai câu trả lời **ngữ nghĩa đúng** (LLM judge cho 1 điểm) nhưng không chứa đúng các chuỗi tên đó → `recall = 0/3 = 0,00`.

- **Nguyên nhân:** `keyword_recall` (`bench_kg.py:46-47`) dùng `k.lower() in answer.lower()` — khớp **chuỗi con chính xác**, không hiểu đồng nghĩa/viết tắt/mô tả. Gold dùng tên người ("Cái Quang Huy") còn câu trả lời dùng tên vụ ("Vụ vận chuyển ma túy từ Đức"). Đây là lỗi của **chính phép đo**, không phải của pipeline; nếu chỉ nhìn `recall` sẽ kết luận sai rằng GraphRAG "không cải thiện" ở Q6.

- **Đề xuất sửa:** bổ sung accepted-aliases vào `must_include` (ví dụ thêm "Đức", "vận chuyển từ Đức") hoặc thay `keyword_recall` bằng khớp ngữ nghĩa/chuẩn hóa (bỏ dấu, gộp biến thể), và luôn đọc `judge` song song. Đánh đổi: thêm alias phải làm tay và có nguy cơ nới lỏng thước đo; dùng embedding để chấm recall tốn thêm ~1 lần gọi/câu.

---

### Lỗi E3: Trùng/đồng nghĩa thực thể — chất và người không được chuẩn hóa (lỗi ở ontology + trích xuất)

- **Hiện tượng:** cùng một chất bị tách thành nhiều node `Substance` (khác hoa/thường và tên lóng), làm đường `Case -INVOLVES-> Substance <-MENTIONS- Clause` nối thiếu/loạn và ảnh hưởng cả Q5, Q6.

- **Bằng chứng (query trên graph thật):**
  ```cypher
  MATCH (s:Substance) RETURN s.name ORDER BY toLower(s.name);
  ```
  ```
  Amphetamine, chất ma túy, Cocaine, côca, cần sa, etomidate, Heroine,
  Ketamine, ketamine, ma túy, ma túy tổng hợp, MDMA, Methamphetamine,
  methamphetamine, thuốc lắc, thuốc phiện, XLR-11
  ```
  → có node trùng rõ ràng: **`Ketamine` vs `ketamine`**, **`Methamphetamine` vs `methamphetamine`**, và các "chất" rác `ma túy`, `chất ma túy`, `ma túy tổng hợp`, `thuốc lắc`, `etomidate`. Vì khóa `MERGE` là `name` phân biệt hoa/thường, hai node không gộp.

  Bằng chứng bổ trợ bằng `find_substances` (trên text tin):
  ```
  find_substances('thuốc lắc') -> []      find_substances('etomidate') -> []
  find_substances('nước vui')  -> []      find_substances('ma túy đá') -> []
  ```
  → các tên lóng không bao giờ khớp danh sách chuẩn, nên không nối được vào khoản luật tương ứng.

- **Nguyên nhân:** `Substance` khóa theo `name` nhưng chuẩn hóa được giao **một phần** cho prompt LLM ("dùng tên chuẩn nếu khớp"); LLM không luôn tuân thủ nên sinh ra `ketamine` thường và cả `etomidate`/`thuốc lắc`. Không có bước `link_entity`/chuẩn hóa hoa-thường cho `Substance`, và danh sách `SUBSTANCES` (`src/graph.py:35`) không có từ điển đồng nghĩa. Tương tự, `Person`/`Case` khóa theo tên LLM tự đặt nên cùng một người ở nhiều bài có thể thành nhiều node (ví dụ `Dương Minh Tuấn` xuất hiện trong nhiều `Case` khác nhau).

- **Đề xuất sửa:** thêm `canonical_substance(name)` dùng `link_entity` (chuẩn hóa hoa-thường + `difflib`) và một bảng đồng nghĩa `{MDMA: [thuốc lắc, kẹo], Methamphetamine: [ma túy đá], ...}`; gọi hàm này trong `extract_news_cases` và `find_substances` trước khi `MERGE`. Đánh đổi: từ điển phải bảo trì tay và có nguy cơ gộp nhầm chất; đổi lại cầu nối chất–khoản chính xác hơn, trực tiếp giúp Q5/Q6.

---

### Lỗi E5: LLM lệch với graph — trả sai số Điều dù graph có Điều đúng (lỗi ở seed/KG-3 rồi lan sang prompt trả lời)

- **Hiện tượng:** Q5 hỏi Cái Quang Huy (tội `vận chuyển` = **Điều 250**); câu trả lời GraphRAG nêu **Điều 251** (tội `mua bán`), tức sai Điều dù graph có Điều 250 khoản 4.

- **Bằng chứng (trích `ket_qua_benchmark_kg.txt`, Q5 graph, `recall=0.80 judge=1`):**
  ```
  ... điều luật tương ứng được áp dụng là Điều 251 BLHS khoản 4.
  Khung hình phạt theo điều luật này là bị phạt tù 20 năm, tù chung thân hoặc tử hình.
  ```
  Gold: "**Điều 250 BLHS** ... khoản 4 ... tù 20 năm, tù chung thân hoặc tử hình" → `must_include` chứa `Điều 250` nên `recall` mất 0,2 tại đây.

  Truy vết `context()` cho Q5 cho thấy nó trả khoản của **4 Điều khác nhau** vì seed quá rộng:
  ```
  Điều 249 khoản 1..4   (tàng trữ)
  Điều 250 khoản 1..4   (vận chuyển)  <-- đúng
  Điều 251 khoản 1..4   (mua bán)
  Điều 255 khoản 1      (tổ chức sử dụng)
  ```
  Nguyên nhân seed: `seed_facts` lấy mọi node có `name` xuất hiện trong câu hỏi; câu hỏi chứa chuỗi "ma túy" nên node `Substance {name:'ma túy'}` thành seed, rồi `EXISTS { MATCH (s)--(k) ... }` kéo về **8 Case** (trong đó có vụ 36kg mua bán → Điều 251). Context vì thế trộn 4 Điều, LLM chọn nhầm.

- **Nguyên nhân:** bước chọn seed trong `seed_facts` khớp `name` theo chuỗi con (`toLower($q) CONTAINS toLower(n.name)`) nên tên chất chung chung ("ma túy") khớp gần như mọi vụ; `context()` sau đó mở rộng 1 hop từ **mọi** seed, không ưu tiên Case theo `doc_id` của vector search. LLM bị "ngập" phương án nên chọn Điều phổ biến (251) thay vì Điều đúng (250).

- **Đề xuất sửa:** giới hạn seed/ưu tiên: khi có `doc_ids`, chỉ lấy Case thuộc đúng các `doc_id` đó (thay vì mọi Case kề seed), và loại các `Substance` tên chung ("ma túy", "chất ma túy") khỏi tập seed. Có thể thêm bước rerank: chọn Case có `doc_id` giao với kết quả vector, rồi mới đi sang luật. Đánh đổi: nếu vector search trượt thì fallback theo tên sẽ yếu hơn; nhưng đổi lại context gọn và đúng vụ hơn, giảm hẳn lỗi chọn sai Điều kiểu E5.

## 4. Kết luận (5 điểm)

> **Dùng Knowledge Graph khi câu hỏi cần ghép ≥ 2 nguồn hoặc gom nhóm.** Bằng số liệu: trên 4 câu cross-kb/aggregation (Q3–Q6), GraphRAG `judge` 1,50 so với Flat 1,00; riêng hai câu cross-kb thuần (Q3–Q4) Flat trả "Không đủ thông tin" (`recall=0`, `judge=0`) còn GraphRAG nối được tên bị cáo với Điều luật (`Q3 judge=2`). Đây là giá trị cốt lõi: không đoạn văn nào chứa cả hai KB, chỉ graph mới nối.
>
> **Flat RAG là đủ khi đáp án nằm gọn trong một tài liệu.** Q1, Q2 cả hai pipeline đều `recall=1,00 / judge=2`; GraphRAG chỉ tốn gấp 3,85× USD/câu và gấp 4,40× token mà không tăng chất lượng.
>
> **Điều kiện cụ thể để KG "đáng tiền":**
> - *Loại dữ liệu:* nhiều KB có khóa chung (ở đây là tội danh) — graph làm cầu nối. Một KB đơn lẻ thì GraphRAG gần như thừa.
> - *Loại câu hỏi:* cross-kb / multi-hop / aggregation. Với single-hop, chi phí tăng không đổi lại lợi ích.
> - *Số câu hỏi:* chi phí dựng graph một lần là **$0,00834** (20 lần gọi LLM); `Q* ≈ 23` câu mới hòa vốn. Với 6 câu như benchmark, Flat rẻ hơn về tổng USD; nhưng vì KG còn tái dùng cho phân tích/truy vấn khác, `Q*` nhanh chóng đạt được trong vận hành thật.
> - *Chất lượng trích xuất:* lợi thế chỉ có nếu cầu nối chắc. E2/E3/E5 cho thấy hạn chế danh sách chất, không mô hình hóa khung tối đa, và seed quá rộng có thể làm GraphRAG **vừa đắt vừa sai** (Q5 sai Điều, Q4 thiếu khung). Sửa ba điểm này (từ điển đồng nghĩa, lấy khoản nặng nhất, seed theo `doc_id`) có chi phí nhỏ so với lợi ích.

## 5. Tự kiểm (5 điểm)

```
$ pytest tests/ -q
................................................
48 passed in 0.06s
```

```
$ python bench_kg.py --check
[OK] Dữ liệu: 18 điều luật, 20 bài báo
[OK] KG-1 link_entity
[OK] Neo4j kết nối được
[provider] chat = openai:gpt-4o-mini | embedding = openai:text-embedding-3-small
[OK] KG-2 build_graph: 146 node / 289 cạnh, đường xuyên 2 KB dài 2 cạnh
[OK] KG-3 context: 13 dữ kiện, có Điều 251
[OK] KG-4 GraphRAGAgent.answer
[OK] Chi phí check: 1 lần gọi LLM, $0.00064. Graph nhỏ (luật + 1 bài) vẫn còn trong Neo4j để bạn xem; chạy --judge để dựng graph đầy đủ.
```

Ảnh Neo4j: `report/img/kg_count.png`, `report/img/kg_cross_kb.png`, `report/img/kg_my_case.png`. Chụp màn hình Neo4j Browser (http://127.0.0.1:7474) với graph đang chạy cục bộ Neo4j Community 5.26 (206 node / 386 cạnh) theo các truy vấn:
- **kg_count.png (Q-A):** `MATCH (n) RETURN labels(n), count(n)` → Article=18, Case=15, Clause=99, Crime=13, Location=7, Person=37, Substance=17 (tổng 206).
- **kg_cross_kb.png (Q-B):** `MATCH (k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)-[:MENTIONS]->(s:Substance) RETURN * LIMIT 25` → ví dụ `Vụ ... Sầm Sơn → Điều 249 khoản 2 → MDMA/Cocaine/Heroine/...`.
- **kg_my_case.png (Q-D):** `MATCH (p:Person)-[:INVOLVED_IN]->(k:Case) WHERE toLower(p.name) CONTAINS 'dương minh tuấn' RETURN k, p LIMIT 5` → 4 Case liên kết Person{name:"Dương Minh Tuấn"}→Case (cross-KB ngay trong graph).

Người đã chọn cho `kg_my_case.png`: **Dương Minh Tuấn (biệt danh "Hoàng Nato")** — 4 Case liên kết qua `Person`-`INVOLVED_IN`->`Case`.

## Vấn đề gặp phải (không tính điểm)

> Máy chạy báo cáo **không có Docker Desktop** (`docker: command not found`) nhưng có Java 21, nên đã dựng **Neo4j Community 5.26 chạy trực tiếp** (`/tmp/neo4j-community-5.26.0`, `neo4j-admin dbms set-initial-password password123`, `neo4j start`), rồi trỏ `NEO4J_URI=bolt://localhost:7687`. Nhờ vậy chạy được đầy đủ `--check` (7 `[OK]`) và `--judge`.
> **Đã chạy được:** `pytest tests/ -q` → 48 passed; `python bench_kg.py --check` → 7 `[OK]`; `python bench_kg.py --judge` → sinh `ket_qua_benchmark_kg.txt` (206 node / 386 cạnh, 176 chunk, chat `gpt-4o-mini`).
> **Lưu ý bảo mật:** `.env` chứa API key đã có trong ổ đĩa nhưng **không** được commit (đã nằm trong `.gitignore`). Không dán key vào báo cáo hay code.
> **Còn lại cần làm thủ công:** mở Neo4j Browser (http://localhost:7474) chạy Q-A/Q-B/Q-D và chụp 3 ảnh vào `report/img/` đúng quy cách (thấy ô truy vấn + Results overview). Graph đang có sau `--judge` là graph đầy đủ.
