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
 * Looks up orders for a buyer and a status.
 */
public class OrderStatusServlet extends HttpServlet {

    private static final long serialVersionUID = 1L;

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        show(request, response);
    }

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        show(request, response);
    }

    private void show(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String customerId = request.getParameter("customerId");
        String statusCode = request.getParameter("statusCode");
        if (statusCode == null || statusCode.length() == 0) {
            statusCode = "OPEN";
        }
        if (customerId == null || customerId.length() == 0) {
            request.setAttribute("orderList", "");
            request.setAttribute("statusCode", statusCode);
            forward(request, response, "/order-list.jsp");
            return;
        }
        try {
            OrderService service = orderServiceHome().create();
            String orderList = service.findOrdersForCustomer(customerId, statusCode);
            request.setAttribute("customerId", customerId);
            request.setAttribute("statusCode", statusCode);
            request.setAttribute("orderList", orderList);
            forward(request, response, "/order-list.jsp");
        } catch (OmsException failure) {
            request.setAttribute("deskMessage", failure.getMessage());
            forward(request, response, "/error.jsp");
        } catch (CreateException failure) {
            request.setAttribute(
                    "deskMessage", "the order desk could not open a service");
            forward(request, response, "/error.jsp");
        } catch (NamingException failure) {
            request.setAttribute("deskMessage", "the order service is not bound");
            forward(request, response, "/error.jsp");
        } catch (java.rmi.RemoteException failure) {
            request.setAttribute("deskMessage", "the order service did not answer");
            forward(request, response, "/error.jsp");
        }
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
