# 🧪 Research-Grade Benchmark Evaluation Report

## 📊 Aggregate Metrics

| Metric | Value |
| :--- | :--- |
| Total Queries | 100 |
| Verified Ground Truth | 100 |
| Execution Accuracy | 100.0% |
| Exact SQL Accuracy | 0.0% |
| Normalized SQL Accuracy | 0.0% |
| Result Correctness | 1.0% |
| Table Selection Accuracy | 84.17% |
| Invalid SQL Rate | 0.0% |
| Hallucinated Schema Rate | 0.0% |
| Unsafe SQL Rate | 0.0% |
| Avg Latency | 7.09s |
| Min Latency | 1.68s |
| Max Latency | 14.08s |
| Avg Confidence | 0.9168 |
| Model Version | auto |

## Per-Query Results

| # | Category | Question | Exec | Exact | Result | Tables | Failure |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| 1 | Revenue & Sales | `What is the total revenue generated?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 2 | Revenue & Sales | `What is the monthly revenue trend?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 3 | Revenue & Sales | `Which month had the highest revenue?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 4 | Revenue & Sales | `Which month had the lowest revenue?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 24, expected 1 |
| 5 | Revenue & Sales | `What is the average order value (AOV)?` | ✅ | ❌ | ✅ | 100% | None |
| 6 | Revenue & Sales | `How has AOV changed over time?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 7 | Revenue & Sales | `What percentage of revenue comes from top 10% cust` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 8 | Revenue & Sales | `Which days of the week generate the most revenue?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 7 |
| 9 | Revenue & Sales | `What is the revenue distribution by hour of the da` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 24 |
| 10 | Revenue & Sales | `What is the revenue growth rate month-over-month?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 24 |
| 11 | Revenue & Sales | `What is the cumulative revenue over time?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 12 | Revenue & Sales | `Which payment type contributes most to revenue?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 13 | Revenue & Sales | `What is the median order value?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 14 | Revenue & Sales | `What is the revenue per customer?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 15 | Revenue & Sales | `What is the revenue per order?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 50 |
| 16 | Orders & Transactions | `How many total orders are there?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 17 | Orders & Transactions | `How many orders per month?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 24, expected 25 |
| 18 | Orders & Transactions | `What is the average number of items per order?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 19 | Orders & Transactions | `What is the distribution of order sizes?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 17 |
| 20 | Orders & Transactions | `How many orders are completed vs cancelled?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 1, expected 8 |
| 21 | Orders & Transactions | `What is the cancellation rate?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 22 | Orders & Transactions | `How long does it take to deliver orders on average` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 23 | Orders & Transactions | `What is the order processing time (purchase -> shi` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 24 | Orders & Transactions | `What percentage of orders are delivered late?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 25 | Orders & Transactions | `What is the trend of late deliveries over time?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 24, expected 23 |
| 26 | Orders & Transactions | `What is the busiest day for orders?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 27 | Orders & Transactions | `What is the peak hour for order placement?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 28 | Orders & Transactions | `What is the average time between orders for a cust` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 29 | Orders & Transactions | `What is the repeat order rate?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 50, expected 1 |
| 30 | Orders & Transactions | `How many orders contain multiple sellers?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 31 | Customers | `How many unique customers are there?` | ✅ | ❌ | ❌ | 0% | Wrong Tables |
| 32 | Customers | `How many new customers per month?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 33 | Customers | `What is the customer retention rate?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 25 |
| 34 | Customers | `What is the churn rate?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 24 |
| 35 | Customers | `What is the average number of orders per customer?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 36 | Customers | `What percentage of customers are repeat buyers?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 1 |
| 37 | Customers | `Which regions have the most customers?` | ✅ | ❌ | ❌ | 0% | Wrong Tables |
| 38 | Customers | `What is the distribution of customers by state?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 27 |
| 39 | Customers | `What is the average revenue per customer (ARPU)?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 40 | Customers | `Who are the top 10 customers by revenue?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 41 | Customers | `What is the lifetime value (LTV) of customers?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 42 | Customers | `How long do customers stay active?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 43 | Customers | `What is the average time between first and last pu` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 44 | Customers | `What percentage of customers make only one purchas` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 45 | Customers | `What is the geographic distribution of high-value ` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 46 | Products & Categories | `Which product categories generate the most revenue` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 47 | Products & Categories | `Which product categories have the most orders?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 48 | Products & Categories | `What is the average price per product category?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 50 |
| 49 | Products & Categories | `Which products are most frequently purchased?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 50 | Products & Categories | `Which products generate the most revenue?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 51 | Products & Categories | `What is the distribution of product prices?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 5 |
| 52 | Products & Categories | `Which categories have the highest AOV?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 1, expected 10 |
| 53 | Products & Categories | `Which categories have declining sales trends?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 24, expected 10 |
| 54 | Products & Categories | `Which categories have the fastest growth?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 55 | Products & Categories | `What is the average number of items sold per produ` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 56 | Products & Categories | `Which products are often bought together? (basic c` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 57 | Products & Categories | `What is the revenue contribution of top categories` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 58 | Products & Categories | `Which products have the highest return/cancellatio` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 1, expected 10 |
| 59 | Products & Categories | `What is the price vs sales relationship?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 5 |
| 60 | Products & Categories | `Which categories have seasonal demand patterns?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 61 | Logistics & Delivery | `What is the average delivery time?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 62 | Logistics & Delivery | `What is the average shipping delay?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 63 | Logistics & Delivery | `Which states have the longest delivery times?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 10 |
| 64 | Logistics & Delivery | `Which sellers deliver the fastest?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 65 | Logistics & Delivery | `What percentage of deliveries are delayed?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 66 | Logistics & Delivery | `What is the trend of delivery delays over time?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 23 |
| 67 | Logistics & Delivery | `How does distance affect delivery time? (approx vi` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 68 | Logistics & Delivery | `Which regions have the best delivery performance?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 69 | Logistics & Delivery | `What is the distribution of delivery times?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 10, expected 5 |
| 70 | Logistics & Delivery | `Are late deliveries increasing or decreasing?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 24, expected 23 |
| 71 | Sellers | `How many sellers are there?` | ✅ | ❌ | ❌ | 0% | Wrong Tables |
| 72 | Sellers | `Which sellers generate the most revenue?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 10 |
| 73 | Sellers | `Which sellers have the most orders?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 10 |
| 74 | Sellers | `What is the average revenue per seller?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 75 | Sellers | `Which sellers have the highest ratings?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 76 | Sellers | `Which sellers have the most delayed deliveries?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 10 |
| 77 | Sellers | `What is the distribution of sellers by region?` | ✅ | ❌ | ❌ | 0% | Wrong Tables |
| 78 | Sellers | `Which sellers are growing fastest?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 24, expected 10 |
| 79 | Sellers | `What is the average delivery time per seller?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 80 | Sellers | `Which sellers have the highest cancellation rate?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 10 |
| 81 | Payments | `Which payment method is most used?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 82 | Payments | `What is the revenue by payment type?` | ✅ | ❌ | ❌ | 100% | value_mismatch |
| 83 | Payments | `What is the average payment value?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 84 | Payments | `How many installments are used on average?` | ✅ | ❌ | ❌ | 0% | Wrong Tables |
| 85 | Payments | `What is the distribution of installment payments?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 24 |
| 86 | Payments | `Do installment payments affect order value?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 24 |
| 87 | Payments | `What is the failure rate of payments?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 88 | Payments | `Which payment types have highest order value?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 5 |
| 89 | Payments | `How does payment method vary by region?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 90 | Payments | `What is the trend of payment methods over time?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 91 | Reviews & Satisfaction | `What is the average review score?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 92 | Reviews & Satisfaction | `What is the distribution of review scores?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 5 |
| 93 | Reviews & Satisfaction | `Which products have the best reviews?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 10 |
| 94 | Reviews & Satisfaction | `Which sellers have the worst reviews?` | ✅ | ❌ | ❌ | 50% | Wrong Tables |
| 95 | Reviews & Satisfaction | `What is the relationship between delivery time and` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 50 |
| 96 | Reviews & Satisfaction | `Do late deliveries lead to lower ratings?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 2 |
| 97 | Reviews & Satisfaction | `What percentage of orders receive reviews?` | ✅ | ❌ | ❌ | 100% | row_count_mismatch: got 9, expected 1 |
| 98 | Reviews & Satisfaction | `What is the trend of review scores over time?` | ✅ | ❌ | ❌ | 0% | Wrong Tables |
| 99 | Reviews & Satisfaction | `Which categories have the highest satisfaction?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |
| 100 | Reviews & Satisfaction | `Which categories have the lowest satisfaction?` | ✅ | ❌ | ❌ | 67% | Wrong Tables |

## Ground Truth Details

- **Source**: manually_verified_gold_sql_against_sqlite_olist
- **Queries with verified ground truth**: 100/100
- **Queries without verified ground truth**: 0

## Failure Breakdown

| Failure Mode | Count | Rate |
| :--- | :---: | :---: |
| Wrong Result | 70 | 70.0% |
| Wrong Tables | 29 | 29.0% |
