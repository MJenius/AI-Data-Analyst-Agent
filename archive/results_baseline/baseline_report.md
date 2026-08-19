# NL-to-SQL Baseline Report

**Date:** 2026-08-15 15:51:58 India Standard Time

## Aggregate Metrics

| Metric | Value |
| :--- | :--- |
| Total Queries | 100 |
| Execution Accuracy | 100.0% |
| Exact SQL Accuracy | UNAVAILABLE - no expected SQL strings in benchmark dataset |
| Invalid SQL Rate | 0.0% |
| Hallucinated Schema Rate | 0.0% |
| Unsafe SQL Rate | 0.0% |
| Avg Latency | 7.09s |
| Avg Confidence | 0.9168 |
| Avg Table Accuracy | 84.17% |
| Token Usage | UNAVAILABLE - LLM clients do not expose token counts in current implementation |

## Model/Version

- **llm_provider**: auto
- **groq_model**: llama-3.3-70b-versatile
- **gemini_model**: gemini-1.5-flash
- **ollama_model**: qwen2.5-coder:7b
- **db_path**: C:\Users\mjeni\OneDrive\Desktop\Own Projects\Data Analyst Agent\runtime\analytics.db
- **log_level**: INFO

## Per-Query Results

- ✅ `What is the total revenue generated?` | Revenue & Sales | 14.08s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the monthly revenue trend?` | Revenue & Sales | 7.81s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which month had the highest revenue?` | Revenue & Sales | 10.86s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which month had the lowest revenue?` | Revenue & Sales | 7.97s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average order value (AOV)?` | Revenue & Sales | 1.68s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How has AOV changed over time?` | Revenue & Sales | 6.47s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What percentage of revenue comes from top 10% customers?` | Revenue & Sales | 12.34s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `Which days of the week generate the most revenue?` | Revenue & Sales | 9.65s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the revenue distribution by hour of the day?` | Revenue & Sales | 8.03s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the revenue growth rate month-over-month?` | Revenue & Sales | 8.9s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the cumulative revenue over time?` | Revenue & Sales | 4.35s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which payment type contributes most to revenue?` | Revenue & Sales | 7.54s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the median order value?` | Revenue & Sales | 4.71s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the revenue per customer?` | Revenue & Sales | 7.9s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `What is the revenue per order?` | Revenue & Sales | 8.0s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How many total orders are there?` | Orders & Transactions | 5.23s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How many orders per month?` | Orders & Transactions | 3.83s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average number of items per order?` | Orders & Transactions | 7.21s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the distribution of order sizes?` | Orders & Transactions | 8.98s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How many orders are completed vs cancelled?` | Orders & Transactions | 3.71s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the cancellation rate?` | Orders & Transactions | 2.71s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How long does it take to deliver orders on average?` | Orders & Transactions | 7.28s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the order processing time (purchase -> shipped)?` | Orders & Transactions | 5.59s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What percentage of orders are delivered late?` | Orders & Transactions | 7.67s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the trend of late deliveries over time?` | Orders & Transactions | 6.87s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the busiest day for orders?` | Orders & Transactions | 4.5s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the peak hour for order placement?` | Orders & Transactions | 6.25s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average time between orders for a customer?` | Orders & Transactions | 12.09s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the repeat order rate?` | Orders & Transactions | 12.36s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How many orders contain multiple sellers?` | Orders & Transactions | 3.9s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How many unique customers are there?` | Customers | 3.89s | tables=0.0% | hallucinated=[] | unsafe=[]
- ✅ `How many new customers per month?` | Customers | 5.33s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the customer retention rate?` | Customers | 7.83s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the churn rate?` | Customers | 9.81s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average number of orders per customer?` | Customers | 5.95s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What percentage of customers are repeat buyers?` | Customers | 13.82s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which regions have the most customers?` | Customers | 7.99s | tables=0.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the distribution of customers by state?` | Customers | 11.94s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average revenue per customer (ARPU)?` | Customers | 11.2s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `Who are the top 10 customers by revenue?` | Customers | 8.39s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `What is the lifetime value (LTV) of customers?` | Customers | 7.53s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `How long do customers stay active?` | Customers | 7.84s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average time between first and last purchase?` | Customers | 7.8s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What percentage of customers make only one purchase?` | Customers | 7.92s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the geographic distribution of high-value customers?` | Customers | 7.61s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `Which product categories generate the most revenue?` | Products & Categories | 12.18s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which product categories have the most orders?` | Products & Categories | 9.38s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average price per product category?` | Products & Categories | 9.35s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which products are most frequently purchased?` | Products & Categories | 8.18s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which products generate the most revenue?` | Products & Categories | 7.91s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the distribution of product prices?` | Products & Categories | 5.88s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which categories have the highest AOV?` | Products & Categories | 5.76s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which categories have declining sales trends?` | Products & Categories | 11.86s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which categories have the fastest growth?` | Products & Categories | 13.02s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average number of items sold per product?` | Products & Categories | 9.15s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which products are often bought together? (basic co-occurrence)` | Products & Categories | 7.24s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the revenue contribution of top categories?` | Products & Categories | 7.63s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which products have the highest return/cancellation rate?` | Products & Categories | 3.33s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the price vs sales relationship?` | Products & Categories | 8.19s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which categories have seasonal demand patterns?` | Products & Categories | 7.67s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average delivery time?` | Logistics & Delivery | 8.26s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average shipping delay?` | Logistics & Delivery | 8.26s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which states have the longest delivery times?` | Logistics & Delivery | 12.71s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers deliver the fastest?` | Logistics & Delivery | 5.45s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `What percentage of deliveries are delayed?` | Logistics & Delivery | 8.24s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the trend of delivery delays over time?` | Logistics & Delivery | 8.66s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How does distance affect delivery time? (approx via location)` | Logistics & Delivery | 5.93s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `Which regions have the best delivery performance?` | Logistics & Delivery | 7.35s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the distribution of delivery times?` | Logistics & Delivery | 4.28s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Are late deliveries increasing or decreasing?` | Logistics & Delivery | 5.82s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How many sellers are there?` | Sellers | 2.89s | tables=0.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers generate the most revenue?` | Sellers | 4.9s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers have the most orders?` | Sellers | 4.56s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average revenue per seller?` | Sellers | 3.98s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers have the highest ratings?` | Sellers | 3.02s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers have the most delayed deliveries?` | Sellers | 5.07s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the distribution of sellers by region?` | Sellers | 4.18s | tables=0.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers are growing fastest?` | Sellers | 5.83s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average delivery time per seller?` | Sellers | 1.88s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers have the highest cancellation rate?` | Sellers | 5.18s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which payment method is most used?` | Payments | 6.04s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the revenue by payment type?` | Payments | 4.2s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average payment value?` | Payments | 5.96s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How many installments are used on average?` | Payments | 6.32s | tables=0.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the distribution of installment payments?` | Payments | 5.95s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Do installment payments affect order value?` | Payments | 6.38s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the failure rate of payments?` | Payments | 6.77s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which payment types have highest order value?` | Payments | 6.61s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `How does payment method vary by region?` | Payments | 6.51s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `What is the trend of payment methods over time?` | Payments | 8.22s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the average review score?` | Reviews & Satisfaction | 6.21s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the distribution of review scores?` | Reviews & Satisfaction | 6.52s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which products have the best reviews?` | Reviews & Satisfaction | 7.2s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Which sellers have the worst reviews?` | Reviews & Satisfaction | 2.37s | tables=50.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the relationship between delivery time and review score?` | Reviews & Satisfaction | 6.23s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `Do late deliveries lead to lower ratings?` | Reviews & Satisfaction | 5.37s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What percentage of orders receive reviews?` | Reviews & Satisfaction | 5.47s | tables=100.0% | hallucinated=[] | unsafe=[]
- ✅ `What is the trend of review scores over time?` | Reviews & Satisfaction | 6.07s | tables=0.0% | hallucinated=[] | unsafe=[]
- ✅ `Which categories have the highest satisfaction?` | Reviews & Satisfaction | 6.91s | tables=66.67% | hallucinated=[] | unsafe=[]
- ✅ `Which categories have the lowest satisfaction?` | Reviews & Satisfaction | 6.92s | tables=66.67% | hallucinated=[] | unsafe=[]
