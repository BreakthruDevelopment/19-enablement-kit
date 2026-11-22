-- Harbor OMS physical model. Synthetic tables for the order desk.

-- A buyer the order desk can sell to. Credit and hold status live on this row.
CREATE TABLE customer (
    -- customerId (String)
    customer_id VARCHAR(32) NOT NULL,
    -- legalName (String)
    legal_name VARCHAR(120) NULL,
    -- regionCode (String)
    region_code VARCHAR(8) NULL,
    -- creditLimitCents (long)
    credit_limit_cents BIGINT NULL,
    -- statusCode (String)
    status_code VARCHAR(16) NULL,
    -- buyerName (String)
    buyer_name VARCHAR(80) NULL,
    -- city (String)
    city VARCHAR(80) NULL,
    -- openedOn (String)
    opened_on VARCHAR(10) NULL
    , CONSTRAINT pk_customer PRIMARY KEY (customer_id)
);

-- A sku stocked in one warehouse. The desk reserves quantity off on_hand.
CREATE TABLE product (
    -- sku (String)
    sku VARCHAR(32) NOT NULL,
    -- description (String)
    description VARCHAR(200) NULL,
    -- unitPriceCents (long)
    unit_price_cents BIGINT NULL,
    -- onHand (int)
    on_hand INTEGER NULL,
    -- warehouseCode (String)
    warehouse_code VARCHAR(16) NULL,
    -- reorderPoint (int)
    reorder_point INTEGER NULL,
    -- activeFlag (String)
    active_flag VARCHAR(1) NULL,
    -- vendorCode (String)
    vendor_code VARCHAR(32) NULL
    , CONSTRAINT pk_product PRIMARY KEY (sku)
);

-- One desk order for one sku. The line row is written with the order.
CREATE TABLE sales_order (
    -- orderId (String)
    order_id VARCHAR(32) NOT NULL,
    -- customerId (String)
    customer_id VARCHAR(32) NULL,
    -- statusCode (String)
    status_code VARCHAR(16) NULL,
    -- placedOn (String)
    placed_on VARCHAR(10) NULL,
    -- requestedShip (String)
    requested_ship VARCHAR(10) NULL,
    -- totalCents (long)
    total_cents BIGINT NULL,
    -- currencyCode (String)
    currency_code VARCHAR(3) NULL,
    -- buyerPo (String)
    buyer_po VARCHAR(40) NULL,
    -- warehouseCode (String)
    warehouse_code VARCHAR(16) NULL,
    -- lineSku (String)
    line_sku VARCHAR(32) NULL,
    -- lineQuantity (int)
    line_quantity INTEGER NULL
    , CONSTRAINT pk_sales_order PRIMARY KEY (order_id)
);

-- A dock shipment against one order, from staged through delivered.
CREATE TABLE shipment (
    -- shipmentId (String)
    shipment_id VARCHAR(32) NOT NULL,
    -- orderId (String)
    order_id VARCHAR(32) NULL,
    -- carrier (String)
    carrier VARCHAR(40) NULL,
    -- trackingNo (String)
    tracking_no VARCHAR(40) NULL,
    -- shippedOn (String)
    shipped_on VARCHAR(10) NULL,
    -- statusCode (String)
    status_code VARCHAR(16) NULL,
    -- weightGrams (int)
    weight_grams INTEGER NULL,
    -- dockDoor (String)
    dock_door VARCHAR(16) NULL
    , CONSTRAINT pk_shipment PRIMARY KEY (shipment_id)
);

-- One packing line for each desk order.
CREATE TABLE order_line (
    order_id VARCHAR(32) NOT NULL,
    line_no INTEGER NOT NULL,
    sku VARCHAR(32) NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_cents BIGINT NOT NULL,
    CONSTRAINT pk_order_line PRIMARY KEY (order_id, line_no)
);

ALTER TABLE sales_order ADD CONSTRAINT fk_sales_order_customer
    FOREIGN KEY (customer_id) REFERENCES customer (customer_id);
ALTER TABLE order_line ADD CONSTRAINT fk_order_line_order
    FOREIGN KEY (order_id) REFERENCES sales_order (order_id);
ALTER TABLE shipment ADD CONSTRAINT fk_shipment_order
    FOREIGN KEY (order_id) REFERENCES sales_order (order_id);

CREATE INDEX ix_customer_region ON customer (region_code);
CREATE INDEX ix_sales_order_customer_status
    ON sales_order (customer_id, status_code);
CREATE INDEX ix_product_warehouse ON product (warehouse_code);
CREATE INDEX ix_shipment_order ON shipment (order_id);

