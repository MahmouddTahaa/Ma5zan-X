-- ============================================================
--  Dark-Store Inventory Management Database
--  SQL Server Script: Schema + Sample Data (5 Dark Stores)
-- ============================================================

USE master;
GO

IF DB_ID('DarkStoreInventory') IS NOT NULL
    DROP DATABASE DarkStoreInventory;
GO

CREATE DATABASE DarkStoreInventory;
GO

USE DarkStoreInventory;
GO

-- ============================================================
--  SCHEMA
-- ============================================================

-- Category
CREATE TABLE Category
(
    category_id INT PRIMARY KEY IDENTITY(1,1),
    name NVARCHAR(100) NOT NULL,
    requires_cold_chain BIT NOT NULL DEFAULT 0
);

-- Supplier
CREATE TABLE Supplier
(
    supplier_id INT PRIMARY KEY IDENTITY(1,1),
    name NVARCHAR(150) NOT NULL,
    phone NVARCHAR(30),
    email NVARCHAR(150)
);

-- Product
CREATE TABLE Product
(
    product_id INT PRIMARY KEY IDENTITY(1,1),
    category_id INT NOT NULL REFERENCES Category(category_id),
    name NVARCHAR(200) NOT NULL,
    SKU NVARCHAR(50) NOT NULL UNIQUE,
    shelf_life_days INT,
    is_active BIT NOT NULL DEFAULT 1,
    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);

-- Zone
CREATE TABLE Zone
(
    zone_id INT PRIMARY KEY IDENTITY(1,1),
    name NVARCHAR(100) NOT NULL,
    city NVARCHAR(100),
    delivery_fee DECIMAL(10,2),
    Est_time_arrival INT,
    -- minutes
    is_active BIT NOT NULL DEFAULT 1,
    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);

-- Dark-Store
CREATE TABLE Dark_Store
(
    store_id INT PRIMARY KEY IDENTITY(1,1),
    name NVARCHAR(150) NOT NULL,
    city NVARCHAR(100),
    street NVARCHAR(200),
    is_active BIT NOT NULL DEFAULT 1,
    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);

-- Customer
CREATE TABLE Customer
(
    customer_id INT PRIMARY KEY IDENTITY(1,1),
    zone_id INT NOT NULL REFERENCES Zone(zone_id),
    first_name NVARCHAR(100) NOT NULL,
    last_name NVARCHAR(100) NOT NULL,
    phone_number NVARCHAR(30),
    full_address NVARCHAR(300),
    registered_time DATETIME2,
    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);

-- Store_Inventory
CREATE TABLE Store_Inventory
(
    inventory_id INT PRIMARY KEY IDENTITY(1,1),
    store_id INT NOT NULL REFERENCES Dark_Store(store_id),
    product_id INT NOT NULL REFERENCES Product(product_id),
    quantity_on_hand INT NOT NULL DEFAULT 0,
    reorder_point INT NOT NULL DEFAULT 20,
    reorder_quantity INT NOT NULL DEFAULT 100,
    last_updated DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    UNIQUE (store_id, product_id)
);

-- Purchase_Order
CREATE TABLE Purchase_Order
(
    po_id INT PRIMARY KEY IDENTITY(1,1),
    store_id INT NOT NULL REFERENCES Dark_Store(store_id),
    supplier_id INT NOT NULL REFERENCES Supplier(supplier_id),
    status NVARCHAR(50) NOT NULL DEFAULT 'pending',
    -- pending / received / cancelled
    total_price DECIMAL(14,2),
    ordered_at DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    received_at DATETIME2
);

-- Purchase_Order_Item
CREATE TABLE Purchase_Order_Item
(
    po_item_id INT PRIMARY KEY IDENTITY(1,1),
    po_id INT NOT NULL REFERENCES Purchase_Order(po_id),
    product_id INT NOT NULL REFERENCES Product(product_id),
    quantity_ordered INT NOT NULL,
    quantity_received INT NOT NULL DEFAULT 0,
    unit_price DECIMAL(10,2) NOT NULL
);

-- [Order]
CREATE TABLE [Order]
(
    order_id INT PRIMARY KEY IDENTITY(1,1),
    store_id INT NOT NULL REFERENCES Dark_Store(store_id),
    customer_id INT NOT NULL REFERENCES Customer(customer_id),
    status NVARCHAR(50) NOT NULL DEFAULT 'pending',
    -- pending / confirmed / delivered / cancelled
    payment_method NVARCHAR(50),
    sub_total DECIMAL(12,2),
    delivery_fee DECIMAL(8,2),
    total_amount DECIMAL(12,2),
    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);

-- Order_Item
CREATE TABLE Order_Item
(
    order_item_id INT PRIMARY KEY IDENTITY(1,1),
    order_id INT NOT NULL REFERENCES [Order](order_id),
    product_id INT NOT NULL REFERENCES Product(product_id),
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    line_total    AS (quantity * unit_price) PERSISTED
);

-- Order_History
CREATE TABLE Order_History
(
    history_id INT PRIMARY KEY IDENTITY(1,1),
    order_id INT NOT NULL REFERENCES [Order](order_id),
    status NVARCHAR(50) NOT NULL,
    changed_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);

-- Inventory_Transaction
CREATE TABLE Inventory_Transaction
(
    transaction_id INT PRIMARY KEY IDENTITY(1,1),
    store_id INT NOT NULL REFERENCES Dark_Store(store_id),
    product_id INT NOT NULL REFERENCES Product(product_id),
    transaction_type NVARCHAR(50) NOT NULL,
    -- sale / restock / adjustment / return
    order_id INT NULL REFERENCES [Order](order_id),
    po_id INT NULL REFERENCES Purchase_Order(po_id),
    quantity_delta INT NOT NULL,
    -- positive = in, negative = out
    quantity_after INT NOT NULL,
    timestamp_occurred DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);

GO
