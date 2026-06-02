# cost-luru 真实话术示例

下面 5 个 case 来自老板日常用语。Claude 解析时按"触发场景表"拆参数。

---

## Case 1: 单品物流费

**老板说**："录 sku-a 顺丰运费 5 块"

**解析**：
- sku_id=SKU-A
- category=logistics
- item_name=顺丰运费
- unit_cost="5"
- vendor="顺丰"

**复述**：
> "录 SKU-A 物流类「顺丰运费」¥5/件，供应商顺丰，从今天起。对吗？"

**调用**：
```
record_cost(sku_id="SKU-A", category="logistics", item_name="顺丰运费",
            unit_cost="5", vendor="顺丰")
```

---

## Case 2: 共享物流费（不绑 SKU）

**老板说**："顺丰华东全店都是 8 块"

**解析**：
- sku_id=None（共享）
- category=logistics
- item_name=顺丰华东
- unit_cost="8"

**复述**：
> "录共享物流费「顺丰华东」¥8/件，所有 SKU 都用。对吗？"

**调用**：
```
record_cost(sku_id=None, category="logistics", item_name="顺丰华东",
            unit_cost="8")
```

---

## Case 3: 包装料

**老板说**："SKU-B 瓶身 0.5"

**解析**：
- sku_id=SKU-B
- category=product
- item_name=瓶身
- unit_cost="0.5"

**复述**：
> "录 SKU-B 产品类「瓶身」¥0.5/件。对吗？"

**调用**：
```
record_cost(sku_id="SKU-B", category="product", item_name="瓶身",
            unit_cost="0.5")
```

---

## Case 4: 厂家报价（按箱）

**老板说**："C 厂报价 12 块一箱 24 瓶"

**解析**：
- sku_id=None（报价不绑特定 SKU）
- category=partner_quote
- item_name=C 厂报价
- unit_cost="12"
- unit="箱"
- quantity_per_unit="24"
- vendor="C 厂"

**复述**：
> "录 C 厂报价：¥12/箱（每箱 24 瓶），供应商 C 厂。对吗？"

**调用**：
```
record_cost(sku_id=None, category="partner_quote", item_name="C 厂报价",
            unit_cost="12", unit="箱", quantity_per_unit="24", vendor="C 厂")
```

---

## Case 5: 改价（先停旧再录新）

**老板说**："SKU-A 物流费涨到 6 块了"

**解析**：先 query_costs 找旧条 → disable 旧 → record 新

**步骤**：

1. **查旧**：
   ```
   query_costs(sku_id="SKU-A", category="logistics")
   ```
   找到 `cost_item_id=abc-123`（item_name="物流费"，unit_cost=5）

2. **复述给老板**：
   > "找到旧条「物流费 ¥5」（id abc12345），新价 ¥6 替换它。要我先停旧再录新吗？"

3. **老板确认后停旧**（Gate 批一次）：
   ```
   disable_cost_item(cost_item_id="abc-123-...", reason="物流费涨价")
   ```

4. **批好后录新**（再 Gate 批一次）：
   ```
   record_cost(sku_id="SKU-A", category="logistics", item_name="物流费",
               unit_cost="6")
   ```

5. **验**：
   ```
   query_costs(sku_id="SKU-A", category="logistics")
   ```
   确认旧条 is_active=False，新条 unit_cost=6。
