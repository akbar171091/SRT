"""
Author: Akbar Farid
Code Name: SRT PnL Stress Analysis
Date: 2025-03-02
Version: 2.0
Description: 
    Conducts sensitivity analysis on amortisation trigger, and loss rates for a Single Risk Transfer (SRT) product.

Version History:
    - 1.0: Initial version of the code.
    - 2.0:  - Added functionality to plot PnL over time for all stress scenarios with trigger timing of 4.
            - Added functionality to track amortisation type (pro-rata or sequential).
            - Added functionality to compound returns upon receipt.
            - Added functionality to store PnL for all stress scenarios with trigger timing of 4
        
Enhancements/Fixes Needed (in order of priority):
    - NEXT RELEASE:
        - DEBUG: Cashflows turning negative upon switch to sequential amortisation. This isn't correct. 
        - DEBUG: Remaining notional at the end needs to be paid to investor. This isn't happening. 
        - Add maturity and replenishment as function inputs for trade structure flexibility.
        
    - FURTHER RELEASES:         
        - Stress scenarios are defined using a 'multiplier' concept. Functionality to 'load' bespoke loss rate series would be useful.
        - What of front/uniform/back-end loading of loss rates? Is this not a stress we need to apply?
        - Monte Carlo on loss rates would be beneficial. Might be better to introduce into a new codebase to feed into this one.
        - GUI version would be beneficial for non-technical users and in OO program system.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def srt_stress_analysis(
    tranche_size,
    notional_amount,
    coupon_rate,
    annual_loss_rate,
    stress_scenarios,
    trigger_timings,
    cln_price,
    risk_free_rates,
    amortisation_rate
):
    """
    Perform stress analysis on the SRT product.
    
    :param tranche_size: Size of the first-loss tranche
    :param notional_amount: Total notional amount of the SRT structure
    :param coupon_rate: Annual coupon rate of the tranche
    :param annual_loss_rate: Expected annual loss rate (given by CLN seller)
    :param stress_scenarios: List of four different stress loss multipliers
    :param trigger_timings: List of four trigger timings (years)
    :param cln_price: Price paid to the seller for the CLN
    :param risk_free_rates: List of risk-free rates for each year
    :param amortisation_rate: Annual amortisation rate (as a fraction of notional)
    :return: DataFrame with PnL scenarios
    """
    
    maturity = 8  # Fixed maturity of the trade
    replenishment_period = 3  # First 3 years of replenishment
    quarters_per_year = 4  # Convert to quarterly output
    total_quarters = maturity * quarters_per_year
    
    results = []
    base_trigger_time = 4  # Fixed trigger timing for the plot
    pnl_over_time = {stress: [0] * total_quarters for stress in stress_scenarios}  # Store PnL over time for plotting
    
    for i, stress in enumerate(stress_scenarios):
        trigger_time = trigger_timings[i]
        remaining_notional = notional_amount
        tranche_exposure = tranche_size
        pnl = -cln_price  # Initial investment cost
        discounted_pnl = -cln_price  # Discounted PnL
        compounded_cashflows = 0  # Track reinvested returns
        sequential_mode = False  # Track if sequential amortisation has started
        
        for year in range(1, maturity + 1):
            for quarter in range(1, quarters_per_year + 1):
                quarter_index = (year - 1) * quarters_per_year + (quarter - 1)
                annual_losses = (remaining_notional * annual_loss_rate * stress) / quarters_per_year
                principal_payment = 0  # Ensure it is defined before use
                
                if year <= replenishment_period:
                    amortisation_type = "Replenishment"
                    quarterly_coupon = (tranche_exposure * coupon_rate) / quarters_per_year
                    quarterly_cashflow = quarterly_coupon  # No principal return since it's replenished
                else:
                    if year == trigger_time:
                        sequential_mode = True  # Once sequential starts, it stays sequential
                    amortisation_type = "Sequential" if sequential_mode else "Pro-rata"
                    
                    if amortisation_type == "Pro-rata":
                        principal_payment = (tranche_exposure / remaining_notional) * (remaining_notional * amortisation_rate / quarters_per_year)
                        tranche_exposure -= principal_payment
                        remaining_notional *= (1 - amortisation_rate / quarters_per_year)  # Quarterly amortisation
                    else:
                        principal_payment = 0  # No principal for first loss under sequential
                        tranche_exposure -= annual_losses  # First loss takes full impact
                        remaining_notional *= (1 - amortisation_rate / quarters_per_year)
                    
                    quarterly_coupon = (tranche_exposure * coupon_rate) / quarters_per_year
                    quarterly_cashflow = quarterly_coupon + principal_payment
                
                tranche_exposure -= annual_losses
                pnl += quarterly_cashflow
                
                # Compound received cashflows at risk-free rate
                risk_free_rate = risk_free_rates[min(year-1, len(risk_free_rates)-1)] / quarters_per_year
                compounded_cashflows = (compounded_cashflows + quarterly_cashflow) * (1 + risk_free_rate)
                discounted_pnl = compounded_cashflows - cln_price
                
                results.append({
                    "Scenario": f"Stress {i+1}",
                    "Year": year,
                    "Quarter": quarter,
                    "Trigger Time": trigger_time,
                    "Stress Multiplier": stress,
                    "Losses": annual_losses,
                    "Remaining Notional": remaining_notional,
                    "Tranche Exposure": tranche_exposure,
                    "Quarterly Cashflow": quarterly_cashflow,
                    "Amortisation Type": amortisation_type,
                    "PnL": pnl,
                    "Discounted PnL": discounted_pnl
                })
                
                # Store PnL for all stress scenarios with trigger timing of 4
                if trigger_time == base_trigger_time:
                    pnl_over_time[stress][quarter_index] = pnl
    
    # Plot PnL for all stress scenarios with trigger timing of 4
    plt.figure(figsize=(10, 5))
    for stress, pnl_values in pnl_over_time.items():
        plt.plot(range(1, total_quarters + 1), pnl_values, marker='o', linestyle='-', label=f"Stress {stress}")
    plt.xlabel("Quarter")
    plt.ylabel("PnL ($)")
    plt.title("PnL Over Time - All Stress Scenarios (Trigger at Year 4)")
    plt.legend()
    plt.grid()
    plt.show()
    
    return pd.DataFrame(results)

# Example usage:
tranche_size = 50_000_000  # Example tranche size
notional_amount = 500_000_000  # Example total notional
coupon_rate = 0.11  # 11% coupon rate
annual_loss_rate = 0.0006  # 0.06% annual loss rate
stress_scenarios = [1, 1.5, 2, 2.5]  # Stress multipliers
trigger_timings = [4, 5, 6, 7]  # Years when triggers occur
cln_price = 45_000_000  # Price paid to seller for the CLN
risk_free_rates = [0.01] * 8  # Example risk-free rate of 1% per year
amortisation_rate = 0.33  # User-specified annual amortisation rate of 33%

df = srt_stress_analysis(tranche_size, notional_amount, coupon_rate, annual_loss_rate, stress_scenarios, trigger_timings, cln_price, risk_free_rates, amortisation_rate)
print(df)

# Filtering the DataFrame based on conditions
pd.options.display.float_format = '{:,.2f}'.format  # Formats all floats with commas and 2 decimal places
filtered_df = df[(df['Trigger Time'] == 5) & (df['Stress Multiplier'] == 1.5)][['Quarter', 'Amortisation Type','PnL']]

# Print the filtered DataFrame
print(filtered_df)
