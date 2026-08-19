# 🧪 Research-Grade Benchmark Evaluation Report (V3)

## 📊 Aggregate Metrics

| Metric | Value |
| :--- | :--- |
| Total Queries | 100 |
| Service Completion Rate | 100.0% |
| SQL Execution Success Rate | 100.0% |
| Result Correctness | 1.0% |
| Result Equivalence (vs gold SQL) | 1.0% |
| Table Selection Accuracy | 86.0% |
| SQL Form Exact Match | 0.0% |
| SQL Form Normalized Match | 0.0% |
| Invalid SQL Rate | 0.0% |
| Hallucinated Schema Rate | 0.0% |
| Unsafe SQL Rate | 0.0% |
| Avg Latency | 7.09s |
| Avg Confidence | 0.9168 |

## Breakdown by Domain

| Domain | Total | Exec | Correct |
| :--- | :---: | :---: | :---: |
| Customers | 15 | 15 | 0 |
| Logistics & Delivery | 10 | 10 | 0 |
| Orders & Transactions | 15 | 15 | 0 |
| Payments | 10 | 10 | 0 |
| Products & Categories | 15 | 15 | 0 |
| Revenue & Sales | 15 | 15 | 1 |
| Reviews & Satisfaction | 10 | 10 | 0 |
| Sellers | 10 | 10 | 0 |

## Breakdown by Query Type

| Query Type | Total | Exec | Correct |
| :--- | :---: | :---: | :---: |
| aggregation | 40 | 40 | 0 |
| ranking | 26 | 26 | 0 |
| single_value | 14 | 14 | 1 |
| time_series | 17 | 17 | 0 |
| unknown | 3 | 3 | 0 |

## Breakdown by Difficulty

| Difficulty | Total | Exec | Correct |
| :--- | :---: | :---: | :---: |
| easy | 70 | 70 | 1 |
| hard | 4 | 4 | 0 |
| medium | 26 | 26 | 0 |

## Per-Query Results

| # | Domain | Query Type | Question | Service | Exec | Correct | Equiv | Tables | Failure |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | Revenue & Sales | single_value | `What is the total revenue generated?` | Yes | Yes | No | No | 100% | column_mismatch |
| 2 | Revenue & Sales | time_series | `What is the monthly revenue trend?` | Yes | Yes | No | No | 100% | timeseries_value_mismatch: 15 difference |
| 3 | Revenue & Sales | single_value | `Which month had the highest revenue?` | Yes | Yes | No | No | 100% | column_mismatch |
| 4 | Revenue & Sales | single_value | `Which month had the lowest revenue?` | Yes | Yes | No | No | 100% | column_mismatch |
| 5 | Revenue & Sales | single_value | `What is the average order value (AOV)?` | Yes | Yes | Yes | Yes | 100% | None |
| 6 | Revenue & Sales | unknown | `How has AOV changed over time?` | Yes | Yes | No | No | 100% | aggregation_mismatch: 24 differences |
| 7 | Revenue & Sales | aggregation | `What percentage of revenue comes from top 10%` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 8 | Revenue & Sales | ranking | `Which days of the week generate the most reve` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 9 | Revenue & Sales | time_series | `What is the revenue distribution by hour of t` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 24 |
| 10 | Revenue & Sales | time_series | `What is the revenue growth rate month-over-mo` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 24 |
| 11 | Revenue & Sales | time_series | `What is the cumulative revenue over time?` | Yes | Yes | No | No | 100% | timeseries_value_mismatch: 39 difference |
| 12 | Revenue & Sales | single_value | `Which payment type contributes most to revenu` | Yes | Yes | No | No | 100% | column_mismatch |
| 13 | Revenue & Sales | single_value | `What is the median order value?` | Yes | Yes | No | No | 100% | column_mismatch |
| 14 | Revenue & Sales | aggregation | `What is the revenue per customer?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 50 |
| 15 | Revenue & Sales | aggregation | `What is the revenue per order?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 50 |
| 16 | Orders & Transactions | aggregation | `How many total orders are there?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 17 | Orders & Transactions | aggregation | `How many orders per month?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 24, expected 25 |
| 18 | Orders & Transactions | aggregation | `What is the average number of items per order` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 19 | Orders & Transactions | time_series | `What is the distribution of order sizes?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 17 |
| 20 | Orders & Transactions | aggregation | `How many orders are completed vs cancelled?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 1, expected 8 |
| 21 | Orders & Transactions | single_value | `What is the cancellation rate?` | Yes | Yes | No | No | 100% | column_mismatch |
| 22 | Orders & Transactions | single_value | `How long does it take to deliver orders on av` | Yes | Yes | No | No | 100% | column_mismatch |
| 23 | Orders & Transactions | single_value | `What is the order processing time (purchase -` | Yes | Yes | No | No | 100% | column_mismatch |
| 24 | Orders & Transactions | aggregation | `What percentage of orders are delivered late?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 25 | Orders & Transactions | time_series | `What is the trend of late deliveries over tim` | Yes | Yes | No | No | 100% | row_count_mismatch: got 24, expected 23 |
| 26 | Orders & Transactions | single_value | `What is the busiest day for orders?` | Yes | Yes | No | No | 100% | column_mismatch |
| 27 | Orders & Transactions | single_value | `What is the peak hour for order placement?` | Yes | Yes | No | No | 100% | column_mismatch |
| 28 | Orders & Transactions | aggregation | `What is the average time between orders for a` | Yes | Yes | No | No | 100% | row_count_mismatch: got 50, expected 1 |
| 29 | Orders & Transactions | single_value | `What is the repeat order rate?` | Yes | Yes | No | No | 100% | column_mismatch |
| 30 | Orders & Transactions | aggregation | `How many orders contain multiple sellers?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 31 | Customers | aggregation | `How many unique customers are there?` | Yes | Yes | No | No | 0% | row_count_mismatch: got 10, expected 1 |
| 32 | Customers | aggregation | `How many new customers per month?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 24, expected 25 |
| 33 | Customers | time_series | `What is the customer retention rate?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 25 |
| 34 | Customers | time_series | `What is the churn rate?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 24 |
| 35 | Customers | aggregation | `What is the average number of orders per cust` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 36 | Customers | aggregation | `What percentage of customers are repeat buyer` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 37 | Customers | ranking | `Which regions have the most customers?` | Yes | Yes | No | No | 0% | ranking_mismatch |
| 38 | Customers | time_series | `What is the distribution of customers by stat` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 27 |
| 39 | Customers | aggregation | `What is the average revenue per customer (ARP` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 40 | Customers | ranking | `Who are the top 10 customers by revenue?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 41 | Customers | aggregation | `What is the lifetime value (LTV) of customers` | Yes | Yes | No | No | 100% | row_count_mismatch: got 1, expected 50 |
| 42 | Customers | aggregation | `How long do customers stay active?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 43 | Customers | aggregation | `What is the average time between first and la` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 44 | Customers | aggregation | `What percentage of customers make only one pu` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 1 |
| 45 | Customers | time_series | `What is the geographic distribution of high-v` | Yes | Yes | No | No | 100% | row_count_mismatch: got 24, expected 27 |
| 46 | Products & Categories | ranking | `Which product categories generate the most re` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 47 | Products & Categories | ranking | `Which product categories have the most orders` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 48 | Products & Categories | aggregation | `What is the average price per product categor` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 50 |
| 49 | Products & Categories | ranking | `Which products are most frequently purchased?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 50 | Products & Categories | ranking | `Which products generate the most revenue?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 51 | Products & Categories | time_series | `What is the distribution of product prices?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 5 |
| 52 | Products & Categories | ranking | `Which categories have the highest AOV?` | Yes | Yes | No | No | 100% | insufficient_rows_for_ranking |
| 53 | Products & Categories | ranking | `Which categories have declining sales trends?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 54 | Products & Categories | ranking | `Which categories have the fastest growth?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 55 | Products & Categories | aggregation | `What is the average number of items sold per ` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 56 | Products & Categories | ranking | `Which products are often bought together? (ba` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 57 | Products & Categories | ranking | `What is the revenue contribution of top categ` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 58 | Products & Categories | ranking | `Which products have the highest return/cancel` | Yes | Yes | No | No | 100% | insufficient_rows_for_ranking |
| 59 | Products & Categories | aggregation | `What is the price vs sales relationship?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 5 |
| 60 | Products & Categories | aggregation | `Which categories have seasonal demand pattern` | Yes | Yes | No | No | 100% | aggregation_mismatch: 10 differences |
| 61 | Logistics & Delivery | aggregation | `What is the average delivery time?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 62 | Logistics & Delivery | aggregation | `What is the average shipping delay?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 63 | Logistics & Delivery | ranking | `Which states have the longest delivery times?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 64 | Logistics & Delivery | ranking | `Which sellers deliver the fastest?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 65 | Logistics & Delivery | aggregation | `What percentage of deliveries are delayed?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 66 | Logistics & Delivery | time_series | `What is the trend of delivery delays over tim` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 23 |
| 67 | Logistics & Delivery | aggregation | `How does distance affect delivery time? (appr` | Yes | Yes | No | No | 50% | row_count_mismatch: got 10, expected 50 |
| 68 | Logistics & Delivery | aggregation | `Which regions have the best delivery performa` | Yes | Yes | No | No | 50% | row_count_mismatch: got 9, expected 10 |
| 69 | Logistics & Delivery | time_series | `What is the distribution of delivery times?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 10, expected 5 |
| 70 | Logistics & Delivery | unknown | `Are late deliveries increasing or decreasing?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 24, expected 23 |
| 71 | Sellers | aggregation | `How many sellers are there?` | Yes | Yes | No | No | 0% | row_count_mismatch: got 10, expected 1 |
| 72 | Sellers | ranking | `Which sellers generate the most revenue?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 73 | Sellers | ranking | `Which sellers have the most orders?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 74 | Sellers | aggregation | `What is the average revenue per seller?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 75 | Sellers | ranking | `Which sellers have the highest ratings?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 76 | Sellers | ranking | `Which sellers have the most delayed deliverie` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 77 | Sellers | time_series | `What is the distribution of sellers by region` | Yes | Yes | No | No | 0% | row_count_mismatch: got 9, expected 23 |
| 78 | Sellers | ranking | `Which sellers are growing fastest?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 79 | Sellers | aggregation | `What is the average delivery time per seller?` | Yes | Yes | No | No | 50% | aggregation_mismatch: 10 differences |
| 80 | Sellers | ranking | `Which sellers have the highest cancellation r` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 81 | Payments | single_value | `Which payment method is most used?` | Yes | Yes | No | No | 100% | column_mismatch |
| 82 | Payments | aggregation | `What is the revenue by payment type?` | Yes | Yes | No | No | 100% | aggregation_mismatch: 5 differences |
| 83 | Payments | aggregation | `What is the average payment value?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 84 | Payments | aggregation | `How many installments are used on average?` | Yes | Yes | No | No | 0% | row_count_mismatch: got 9, expected 1 |
| 85 | Payments | time_series | `What is the distribution of installment payme` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 24 |
| 86 | Payments | unknown | `Do installment payments affect order value?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 24 |
| 87 | Payments | single_value | `What is the failure rate of payments?` | Yes | Yes | No | No | 100% | column_mismatch |
| 88 | Payments | ranking | `Which payment types have highest order value?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 89 | Payments | aggregation | `How does payment method vary by region?` | Yes | Yes | No | No | 67% | row_count_mismatch: got 9, expected 50 |
| 90 | Payments | aggregation | `What is the trend of payment methods over tim` | Yes | Yes | No | No | 50% | row_count_mismatch: got 9, expected 50 |
| 91 | Reviews & Satisfaction | aggregation | `What is the average review score?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 92 | Reviews & Satisfaction | time_series | `What is the distribution of review scores?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 5 |
| 93 | Reviews & Satisfaction | ranking | `Which products have the best reviews?` | Yes | Yes | No | No | 100% | ranking_mismatch |
| 94 | Reviews & Satisfaction | ranking | `Which sellers have the worst reviews?` | Yes | Yes | No | No | 50% | ranking_mismatch |
| 95 | Reviews & Satisfaction | aggregation | `What is the relationship between delivery tim` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 50 |
| 96 | Reviews & Satisfaction | aggregation | `Do late deliveries lead to lower ratings?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 2 |
| 97 | Reviews & Satisfaction | aggregation | `What percentage of orders receive reviews?` | Yes | Yes | No | No | 100% | row_count_mismatch: got 9, expected 1 |
| 98 | Reviews & Satisfaction | time_series | `What is the trend of review scores over time?` | Yes | Yes | No | No | 0% | row_count_mismatch: got 9, expected 23 |
| 99 | Reviews & Satisfaction | ranking | `Which categories have the highest satisfactio` | Yes | Yes | No | No | 67% | ranking_mismatch |
| 100 | Reviews & Satisfaction | ranking | `Which categories have the lowest satisfaction` | Yes | Yes | No | No | 67% | ranking_mismatch |

## Evaluation Methodology Notes

- **service_completion**: Agent returned a response (may include fallback SQL)
- **sql_execution_success**: Generated SQL was independently executed against DB without error
- **result_correctness**: Query-type-aware comparison of generated result vs gold result
- **result_equivalence**: Generated result vs gold SQL result (both executed independently)
- **sql_form_similarity**: Text-level SQL similarity, NOT semantic correctness
