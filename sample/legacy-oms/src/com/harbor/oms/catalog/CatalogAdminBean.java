/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.catalog;

import java.io.IOException;
import java.rmi.RemoteException;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;

import javax.ejb.CreateException;
import javax.ejb.EJBException;
import javax.ejb.FinderException;
import javax.ejb.SessionBean;
import javax.ejb.SessionContext;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.rmi.PortableRemoteObject;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.sql.DataSource;

import com.harbor.oms.product.Product;
import com.harbor.oms.product.ProductHome;
import com.harbor.oms.support.OmsException;

/**
 * Adds skus, retires them and moves a sku between warehouses.
 */
public class CatalogAdminBean extends HttpServlet implements SessionBean {

    private SessionContext sessionContext;

    private static final long serialVersionUID = 1L;

    public void ejbCreate() throws RemoteException {
    }

    public void ejbRemove() throws RemoteException {
    }

    public void ejbActivate() throws RemoteException {
    }

    public void ejbPassivate() throws RemoteException {
    }

    public void setSessionContext(SessionContext context) throws RemoteException {
        this.sessionContext = context;
    }

    public void addProduct(String sku, String description, long unitPriceCents, String warehouseCode, String vendorCode) throws OmsException {
        if (sku == null || sku.length() == 0) {
            throw new OmsException("sku is required");
        }
        if (unitPriceCents < 0) {
            throw new OmsException("price must not be negative");
        }
        try {
            productHome().create(
                    sku,
                    description == null ? "" : description,
                    unitPriceCents,
                    0,
                    warehouseCode,
                    0,
                    "Y",
                    vendorCode == null ? "" : vendorCode);
        } catch (CreateException failure) {
            throw new EJBException("catalog create failed for " + sku, failure);
        } catch (NamingException failure) {
            throw new EJBException("catalog lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("catalog call failed", failure);
        }
    }

    public void discontinueProduct(String sku) throws OmsException {
        try {
            Product product = productHome().findByPrimaryKey(sku);
            product.setActiveFlag("N");
        } catch (FinderException missing) {
            throw new OmsException("unknown sku: " + sku);
        } catch (NamingException failure) {
            throw new EJBException("catalog lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("catalog call failed", failure);
        }
    }

    public void updateWarehouse(String sku, String warehouseCode) throws OmsException {
        if (warehouseCode == null || warehouseCode.length() == 0) {
            throw new OmsException("warehouse is required");
        }
        try {
            Product product = productHome().findByPrimaryKey(sku);
            product.setWarehouseCode(warehouseCode);
        } catch (FinderException missing) {
            throw new OmsException("unknown sku: " + sku);
        } catch (NamingException failure) {
            throw new EJBException("catalog lookup failed", failure);
        } catch (RemoteException failure) {
            throw new EJBException("catalog call failed", failure);
        }
    }

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setContentType("text/html; charset=UTF-8");
        response.getWriter().print(catalogForm(request.getContextPath()));
    }

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String sku = request.getParameter("sku");
        String description = request.getParameter("description");
        String priceText = request.getParameter("unitPriceCents");
        String warehouseCode = request.getParameter("warehouseCode");
        String vendorCode = request.getParameter("vendorCode");
        if (sku == null || description == null || priceText == null
                || warehouseCode == null) {
            response.sendError(
                    HttpServletResponse.SC_BAD_REQUEST,
                    "sku, description, price and warehouse are required");
            return;
        }
        long unitPriceCents;
        try {
            unitPriceCents = Long.parseLong(priceText);
        } catch (NumberFormatException failure) {
            response.sendError(
                    HttpServletResponse.SC_BAD_REQUEST, "unit price must be cents");
            return;
        }
        try {
            writeProduct(
                    sku,
                    description,
                    unitPriceCents,
                    warehouseCode,
                    vendorCode == null ? "" : vendorCode);
        } catch (OmsException failure) {
            response.sendError(HttpServletResponse.SC_CONFLICT, failure.getMessage());
            return;
        }
        response.sendRedirect(request.getContextPath() + "/admin/catalog");
    }

    private void writeProduct(
            String sku,
            String description,
            long unitPriceCents,
            String warehouseCode,
            String vendorCode) throws OmsException {
        if (sku.length() == 0 || unitPriceCents < 0) {
            throw new OmsException("sku and a non-negative price are required");
        }
        Connection connection = null;
        try {
            connection = lookupOrderDataSource().getConnection();
            PreparedStatement update = connection.prepareStatement(
                    "UPDATE product SET description = ?, unit_price_cents = ?, "
                            + "warehouse_code = ?, vendor_code = ?, active_flag = 'Y' "
                            + "WHERE sku = ?");
            try {
                update.setString(1, description);
                update.setLong(2, unitPriceCents);
                update.setString(3, warehouseCode);
                update.setString(4, vendorCode);
                update.setString(5, sku);
                int updated = update.executeUpdate();
                if (updated == 0) {
                    insertProduct(
                            connection,
                            sku,
                            description,
                            unitPriceCents,
                            warehouseCode,
                            vendorCode);
                }
            } finally {
                update.close();
            }
        } catch (NamingException failure) {
            throw new EJBException("catalog datasource lookup failed", failure);
        } catch (SQLException failure) {
            throw new EJBException("catalog write failed for " + sku, failure);
        } finally {
            close(connection);
        }
    }

    private void insertProduct(
            Connection connection,
            String sku,
            String description,
            long unitPriceCents,
            String warehouseCode,
            String vendorCode) throws SQLException {
        PreparedStatement insert = connection.prepareStatement(
                "INSERT INTO product (sku, description, unit_price_cents, on_hand, "
                        + "warehouse_code, reorder_point, active_flag, vendor_code) "
                        + "VALUES (?, ?, ?, 0, ?, 0, 'Y', ?)");
        try {
            insert.setString(1, sku);
            insert.setString(2, description);
            insert.setLong(3, unitPriceCents);
            insert.setString(4, warehouseCode);
            insert.setString(5, vendorCode);
            insert.executeUpdate();
        } finally {
            insert.close();
        }
    }

    private String catalogForm(String contextPath) {
        return "<!DOCTYPE html>\n"
                + "<html><head><title>Harbor catalog desk</title></head>\n"
                + "<body><h1>Harbor catalog desk</h1>\n"
                + "<form method=\"post\" action=\"" + contextPath
                + "/admin/catalog\">\n"
                + "<p>SKU <input name=\"sku\"/></p>\n"
                + "<p>Description <input name=\"description\"/></p>\n"
                + "<p>Unit price (cents) <input name=\"unitPriceCents\"/></p>\n"
                + "<p>Warehouse <input name=\"warehouseCode\"/></p>\n"
                + "<p>Vendor <input name=\"vendorCode\"/></p>\n"
                + "<p><button type=\"submit\">Save sku</button></p>\n"
                + "</form></body></html>\n";
    }

    private ProductHome productHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/Product");
        return (ProductHome) PortableRemoteObject.narrow(
                bound, ProductHome.class);
    }

    private DataSource lookupOrderDataSource() throws NamingException {
        InitialContext naming = new InitialContext();
        return (DataSource) naming.lookup("java:comp/env/jdbc/OrderDS");
    }

    private void close(Connection connection) {
        if (connection == null) {
            return;
        }
        try {
            connection.close();
        } catch (SQLException failure) {
            throw new EJBException("failed to close a JDBC connection", failure);
        }
    }
}
