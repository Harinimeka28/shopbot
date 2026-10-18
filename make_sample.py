import csv
R=[("P1001","Stride Blue Running Shoe","Lightweight mesh runner","1999","in stock","Footwear","4.2","color: blue; material: mesh"),
("P1002","Velocity Blue Running Shoe","Cushioned trainer","2799","in stock","Footwear","4.5","color: blue; material: knit"),
("P1003","Jet Blue Running Shoe","Budget runner","1499","out of stock","Footwear","3.9","color: blue; material: synthetic"),
("P1004","Classic Cotton Kurta","Everyday kurta in soft cotton","1299","in stock","Clothing","4.4","color: white; material: cotton"),
("P1005","Festive Cotton Kurta","Embroidered cotton kurta","2499","in stock","Clothing","4.6","color: maroon; material: cotton"),
("P1006","Linen Casual Shirt","Breathable linen shirt","1799","in stock","Clothing","4.1","color: beige; material: linen"),
("P1007","Leather Wallet","Bi-fold wallet","799","in stock","Accessories","4.3","color: brown; material: leather"),
("P1008","Steel Water Bottle","1L insulated bottle","649","in stock","Home","4.7","color: black; material: steel")]
w=csv.writer(open("catalogue.csv","w",newline="",encoding="utf-8"));w.writerow("id title description price stock category rating attributes".split());w.writerows(R)
open("policy.txt","w").write("""Returns
Items can be returned within 15 days of delivery. Products must be unused with original tags. Refunds are processed in 5-7 business days.

Shipping
Standard delivery takes 3-5 business days. Orders above ₹999 ship free.

Warranty
Electronics carry a 1 year warranty. Clothing and footwear have no warranty.
""")
