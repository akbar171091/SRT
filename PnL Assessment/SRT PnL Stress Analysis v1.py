"""
Author: Akbar Farid
Code Name: SRT PnL Stress Analysis
Date: 2021-09-29
Version: 1.0
Description: 
    Conducts sensitivity analysis on amortisation trigger, and loss rates for a Single Risk Transfer (SRT) product.

Version History:
    N/A

Enhancements Needed (in order of priority):
    - NEXT RELEASE:
        - DEBUG/CHECK: Risk-free rate check needed. 
        - DEBUG/CHECK: Once switch to sequential amortisation, should not switch back to pro-rata.
        - Code output is yearly. Quarterly is required.
        - Plot is for one scenario/trigger type. Multiple plots, for multiple scenarios required.
        - Amortisation rate is assumed to be linear. Functionality to put in non-linear profiles pending. 

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
    
    results = []
    
    base_scenario_index = 0  # Index for the first stress scenario
    base_trigger_time = 4  # Fixed trigger timing for the plot
    base_pnl_over_time = []
    
    for i, stress in enumerate(stress_scenarios):
        trigger_time = trigger_timings[i]
        remaining_notional = notional_amount
        tranche_exposure = tranche_size
        pnl = -cln_price  # Initial investment cost
        discounted_pnl = -cln_price  # Discounted PnL
        
        pnl_over_time = []  # To store PnL for plotting
        
        for year in range(1, maturity + 1):
            annual_losses = remaining_notional * annual_loss_rate * stress
            
            if year > replenishment_period:
                if year == trigger_time:
                    amortisation_type = "Sequential"
                else:
                    amortisation_type = "Pro-rata"
                
                if amortisation_type == "Pro-rata":
                    remaining_notional *= (1 - amortisation_rate)  # User-specified amortisation rate
                else:
                    tranche_exposure -= annual_losses  # First loss takes full impact
                    remaining_notional *= (1 - amortisation_rate)
            
            tranche_exposure -= annual_losses
            annual_cashflow = tranche_exposure * coupon_rate
            pnl += annual_cashflow
            
            # Discounted PnL calculation
            discount_factor = np.prod([(1 + risk_free_rates[y-1]) for y in range(1, year + 1)])
            discounted_pnl += annual_cashflow / discount_factor
            
            pnl_over_time.append(pnl)
            
            results.append({
                "Scenario": f"Stress {i+1}",
                "Year": year,
                "Trigger Time": trigger_time,
                "Stress Multiplier": stress,
                "Losses": annual_losses,
                "Remaining Notional": remaining_notional,
                "Tranche Exposure": tranche_exposure,
                "Amortisation Type": amortisation_type if year > replenishment_period else "Replenishment",
                "Annual Cashflow": annual_cashflow, 
                "PnL": pnl,
                "Discounted PnL": discounted_pnl
            })
        
        # Store the PnL for the first stress scenario with trigger timing of 4
        if i == base_scenario_index and trigger_time == base_trigger_time:
            base_pnl_over_time = pnl_over_time
    
    # Plot PnL for the first stress scenario with trigger timing of 4
    if base_pnl_over_time:
        plt.figure(figsize=(10, 5))
        plt.plot(range(1, maturity + 1), base_pnl_over_time, marker='o', linestyle='-', label="First Stress Scenario (Trigger at Year 4)")
        plt.xlabel("Year")
        plt.ylabel("PnL ($)")
        plt.title("PnL Over Time - First Stress Scenario with Trigger at Year 4")
        plt.legend()
        plt.grid()
        plt.show()
    
    return pd.DataFrame(results)

# Example usage:
tranche_size = 50_000_000  # Example tranche size
notional_amount = 500_000_000  # Example total notional
coupon_rate = 0.11  # 11% coupon rate
annual_loss_rate = 0.0004  # 4bps annual loss rate
stress_scenarios = [1, 1.5, 2, 2.5]  # Stress multipliers
trigger_timings = [4, 5, 6, 7]  # Years when triggers occur
cln_price = 35_000_000  # Price paid to seller for the CLN
risk_free_rates = [0.01] * 8  # Example risk-free rate of 1% per year
amortisation_rate = 0.33  # User-specified annual amortisation rate of 33%

df = srt_stress_analysis(tranche_size, notional_amount, coupon_rate, annual_loss_rate, stress_scenarios, trigger_timings, cln_price, risk_free_rates, amortisation_rate)
print(df)

# Filtering the DataFrame based on conditions
pd.options.display.float_format = '{:,.2f}'.format  # Formats all floats with commas and 2 decimal places
filtered_df = df[(df['Trigger Time'] == 4) & (df['Stress Multiplier'] == 1)][['Year', 'PnL', 'Amortisation Type', 'Annual Cashflow']]

# Print the filtered DataFrame
print(filtered_df)
