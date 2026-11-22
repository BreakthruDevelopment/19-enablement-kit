<%@ page contentType="text/html; charset=UTF-8" %>
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Place an order</title>
</head>
<body>
  <h1>Harbor order desk</h1>
  <h2>Place an order</h2>
  <p>
    <a href="index.jsp">Home</a>
    | <a href="order-entry.jsp">New order</a>
    | <a href="order-list.jsp">Order status</a>
  </p>
  <form method="post" action="<%= request.getContextPath() %>/orders/new">
    <p>Customer id<br/><input name="customerId"/></p>
    <p>SKU<br/><input name="sku"/></p>
    <p>Quantity<br/><input name="quantity"/></p>
    <p>Placed on (yyyy-mm-dd)<br/><input name="placedOn"/></p>
    <p>Requested ship (yyyy-mm-dd)<br/><input name="requestedShip"/></p>
    <p>Buyer PO<br/><input name="buyerPo"/></p>
    <p><button type="submit">Place order</button></p>
  </form>
  <p>A held or closed buyer is refused. The sku must be active.</p>
  <hr/>
  <p>Pier office, doors 1 to 4. Stored prices are whole cents.</p>
</body>
</html>
