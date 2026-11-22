/*
 * Harbor OMS. Synthetic order-management code written for this repository.
 */
package com.harbor.oms.web;

import java.io.IOException;

import javax.ejb.CreateException;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.rmi.PortableRemoteObject;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

import com.harbor.oms.order.OrderService;
import com.harbor.oms.order.OrderServiceHome;
import com.harbor.oms.support.OmsException;

/**
 * The desk form that places one order.
 */
public class OrderEntryServlet extends HttpServlet {

    private static final long serialVersionUID = 1L;

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        forward(request, response, "/order-entry.jsp");
    }

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String customerId = request.getParameter("customerId");
        String sku = request.getParameter("sku");
        String quantityText = request.getParameter("quantity");
        String placedOn = request.getParameter("placedOn");
        String requestedShip = request.getParameter("requestedShip");
        String buyerPo = request.getParameter("buyerPo");
        if (customerId == null || sku == null || quantityText == null) {
            fail(request, response, "customer, sku and quantity are required");
            return;
        }
        int quantity;
        try {
            quantity = Integer.parseInt(quantityText);
        } catch (NumberFormatException failure) {
            fail(request, response, "quantity must be a whole number");
            return;
        }
        try {
            OrderService service = orderServiceHome().create();
            String orderId = service.placeOrder(
                    customerId, sku, quantity, placedOn, requestedShip, buyerPo);
            request.setAttribute("orderId", orderId);
            request.setAttribute("customerId", customerId);
            request.setAttribute("sku", sku);
            request.setAttribute("quantity", Integer.valueOf(quantity));
            forward(request, response, "/order-detail.jsp");
        } catch (OmsException failure) {
            fail(request, response, failure.getMessage());
        } catch (CreateException failure) {
            fail(request, response, "the order desk could not open a service");
        } catch (NamingException failure) {
            fail(request, response, "the order service is not bound");
        } catch (java.rmi.RemoteException failure) {
            fail(request, response, "the order service did not answer");
        }
    }

    private void fail(
            HttpServletRequest request, HttpServletResponse response, String message)
            throws ServletException, IOException {
        request.setAttribute("deskMessage", message);
        forward(request, response, "/error.jsp");
    }

    private OrderServiceHome orderServiceHome() throws NamingException {
        InitialContext naming = new InitialContext();
        Object bound = naming.lookup("java:comp/env/ejb/OrderService");
        return (OrderServiceHome) PortableRemoteObject.narrow(
                bound, OrderServiceHome.class);
    }

    private void forward(
            HttpServletRequest request, HttpServletResponse response, String view)
            throws ServletException, IOException {
        request.getRequestDispatcher(view).forward(request, response);
    }
}
