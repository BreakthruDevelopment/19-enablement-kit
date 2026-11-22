-- Sample rows for the Harbor desk. Names are fictional.

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-100',
    'Pier Street Market',
    'NORTH',
    500000,
    'ACTIVE',
    'Ada Shore',
    'Harbor City',
    '2014-04-02'
);

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-110',
    'North Dock Supply',
    'NORTH',
    250000,
    'ACTIVE',
    'Ben Calder',
    'Harbor City',
    '2015-01-19'
);

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-120',
    'Lantern Hill Grocers',
    'SOUTH',
    800000,
    'ACTIVE',
    'Cora Nguyen',
    'Saltmere',
    '2012-11-03'
);

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-130',
    'Westbreak Chandlery',
    'WEST',
    150000,
    'HOLD',
    'Diego Marsh',
    'Cape Rowan',
    '2016-06-28'
);

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-140',
    'Eastwharf Bakery',
    'EAST',
    120000,
    'ACTIVE',
    'Eden Price',
    'Millhaven',
    '2018-02-14'
);

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-150',
    'Keel and Crate',
    'SOUTH',
    640000,
    'ACTIVE',
    'Farah Quinn',
    'Saltmere',
    '2011-09-09'
);

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-160',
    'Blue Buoy Provisions',
    'WEST',
    300000,
    'ACTIVE',
    'Gus Hale',
    'Cape Rowan',
    '2017-05-21'
);

INSERT INTO customer (
    customer_id,
    legal_name,
    region_code,
    credit_limit_cents,
    status_code,
    buyer_name,
    city,
    opened_on
) VALUES (
    'C-170',
    'Closed Pier Cafe',
    'EAST',
    90000,
    'CLOSED',
    'Hana Ito',
    'Millhaven',
    '2009-12-01'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-FLOUR',
    'Stone flour 25kg',
    4200,
    80,
    'DOCK-N',
    20,
    'Y',
    'V-MILL'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-OIL',
    'Lamp oil 12L',
    3100,
    40,
    'DOCK-N',
    10,
    'Y',
    'V-MILL'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-SALT',
    'Bay salt 10kg',
    900,
    120,
    'DOCK-S',
    30,
    'Y',
    'V-SALT'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-ROPE',
    'Manila rope 30m',
    2500,
    15,
    'DOCK-W',
    8,
    'Y',
    'V-CORD'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-NAIL',
    'Copper nails 5kg',
    1800,
    200,
    'DOCK-W',
    40,
    'Y',
    'V-CORD'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-TEA',
    'Dock tea 1kg',
    1500,
    60,
    'DOCK-E',
    12,
    'Y',
    'V-LEAF'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-BEAN',
    'Dry beans 20kg',
    2700,
    50,
    'DOCK-S',
    15,
    'Y',
    'V-MILL'
);

INSERT INTO product (
    sku,
    description,
    unit_price_cents,
    on_hand,
    warehouse_code,
    reorder_point,
    active_flag,
    vendor_code
) VALUES (
    'SKU-SOAP',
    'Galley soap 4kg',
    800,
    10,
    'DOCK-E',
    25,
    'Y',
    'V-LEAF'
);

INSERT INTO sales_order (
    order_id,
    customer_id,
    status_code,
    placed_on,
    requested_ship,
    total_cents,
    currency_code,
    buyer_po,
    warehouse_code,
    line_sku,
    line_quantity
) VALUES (
    'C-100-2024-03-01-SKU-FLOUR',
    'C-100',
    'OPEN',
    '2024-03-01',
    '2024-03-04',
    21000,
    'USD',
    'PO-441',
    'DOCK-N',
    'SKU-FLOUR',
    5
);

INSERT INTO sales_order (
    order_id,
    customer_id,
    status_code,
    placed_on,
    requested_ship,
    total_cents,
    currency_code,
    buyer_po,
    warehouse_code,
    line_sku,
    line_quantity
) VALUES (
    'C-120-2024-03-02-SKU-BEAN',
    'C-120',
    'OPEN',
    '2024-03-02',
    '2024-03-06',
    54000,
    'USD',
    'PO-442',
    'DOCK-S',
    'SKU-BEAN',
    20
);

INSERT INTO sales_order (
    order_id,
    customer_id,
    status_code,
    placed_on,
    requested_ship,
    total_cents,
    currency_code,
    buyer_po,
    warehouse_code,
    line_sku,
    line_quantity
) VALUES (
    'C-140-2024-03-03-SKU-TEA',
    'C-140',
    'ALLOCATED',
    '2024-03-03',
    '2024-03-05',
    15000,
    'USD',
    'PO-443',
    'DOCK-E',
    'SKU-TEA',
    10
);

INSERT INTO sales_order (
    order_id,
    customer_id,
    status_code,
    placed_on,
    requested_ship,
    total_cents,
    currency_code,
    buyer_po,
    warehouse_code,
    line_sku,
    line_quantity
) VALUES (
    'C-150-2024-02-20-SKU-SALT',
    'C-150',
    'SHIPPED',
    '2024-02-20',
    '2024-02-22',
    9000,
    'USD',
    'PO-410',
    'DOCK-S',
    'SKU-SALT',
    10
);

INSERT INTO sales_order (
    order_id,
    customer_id,
    status_code,
    placed_on,
    requested_ship,
    total_cents,
    currency_code,
    buyer_po,
    warehouse_code,
    line_sku,
    line_quantity
) VALUES (
    'C-160-2024-02-11-SKU-ROPE',
    'C-160',
    'DELIVERED',
    '2024-02-11',
    '2024-02-14',
    5000,
    'USD',
    'PO-388',
    'DOCK-W',
    'SKU-ROPE',
    2
);

INSERT INTO sales_order (
    order_id,
    customer_id,
    status_code,
    placed_on,
    requested_ship,
    total_cents,
    currency_code,
    buyer_po,
    warehouse_code,
    line_sku,
    line_quantity
) VALUES (
    'C-110-2024-01-09-SKU-OIL',
    'C-110',
    'CANCELLED',
    '2024-01-09',
    '2024-01-12',
    6200,
    'USD',
    'PO-301',
    'DOCK-N',
    'SKU-OIL',
    2
);

INSERT INTO order_line (
    order_id,
    line_no,
    sku,
    quantity,
    unit_price_cents
) VALUES (
    'C-100-2024-03-01-SKU-FLOUR',
    1,
    'SKU-FLOUR',
    5,
    4200
);

INSERT INTO order_line (
    order_id,
    line_no,
    sku,
    quantity,
    unit_price_cents
) VALUES (
    'C-120-2024-03-02-SKU-BEAN',
    1,
    'SKU-BEAN',
    20,
    2700
);

INSERT INTO order_line (
    order_id,
    line_no,
    sku,
    quantity,
    unit_price_cents
) VALUES (
    'C-140-2024-03-03-SKU-TEA',
    1,
    'SKU-TEA',
    10,
    1500
);

INSERT INTO order_line (
    order_id,
    line_no,
    sku,
    quantity,
    unit_price_cents
) VALUES (
    'C-150-2024-02-20-SKU-SALT',
    1,
    'SKU-SALT',
    10,
    900
);

INSERT INTO order_line (
    order_id,
    line_no,
    sku,
    quantity,
    unit_price_cents
) VALUES (
    'C-160-2024-02-11-SKU-ROPE',
    1,
    'SKU-ROPE',
    2,
    2500
);

INSERT INTO order_line (
    order_id,
    line_no,
    sku,
    quantity,
    unit_price_cents
) VALUES (
    'C-110-2024-01-09-SKU-OIL',
    1,
    'SKU-OIL',
    2,
    3100
);

INSERT INTO shipment (
    shipment_id,
    order_id,
    carrier,
    tracking_no,
    shipped_on,
    status_code,
    weight_grams,
    dock_door
) VALUES (
    'C-140-2024-03-03-SKU-TEA-S1',
    'C-140-2024-03-03-SKU-TEA',
    'Harbor Barge',
    '',
    '',
    'STAGED',
    0,
    'DOOR-1'
);

INSERT INTO shipment (
    shipment_id,
    order_id,
    carrier,
    tracking_no,
    shipped_on,
    status_code,
    weight_grams,
    dock_door
) VALUES (
    'C-150-2024-02-20-SKU-SALT-S1',
    'C-150-2024-02-20-SKU-SALT',
    'Coast Wagon',
    'TRK-150',
    '2024-02-22',
    'SHIPPED',
    10000,
    'DOOR-2'
);

INSERT INTO shipment (
    shipment_id,
    order_id,
    carrier,
    tracking_no,
    shipped_on,
    status_code,
    weight_grams,
    dock_door
) VALUES (
    'C-160-2024-02-11-SKU-ROPE-S1',
    'C-160-2024-02-11-SKU-ROPE',
    'Coast Wagon',
    'TRK-088',
    '2024-02-14',
    'DELIVERED',
    4000,
    'DOOR-3'
);

