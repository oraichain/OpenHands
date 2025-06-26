import asyncio
import csv
import json
import re

from openhands.server.planning.planning import (
    DECIDE_REWRITE_PROMPT,
    REWRITE_QUERY_PROMPT,
    PromptRefiner,
    logger,
    optimize_prompt,
)

asyncio.run(
    optimize_prompt('Analyze a farming pool on Raydium and assess its risk level.')
)


async def test_run(prompt: str):
    refiner = PromptRefiner()
    optimized_prompt = await refiner.generate_response(
        prompt, system_prompt=REWRITE_QUERY_PROMPT
    )
    return optimized_prompt


async def test_rewrite(prompt: str):
    refiner = PromptRefiner()
    optimized_prompt = await refiner.generate_response(
        prompt, system_prompt=DECIDE_REWRITE_PROMPT
    )
    return optimized_prompt


def run_batch():
    prompts = [
        'What is the price of Bitcoin? # 0',
        'Hello # 0',
        'What can you do? # 0',
        'I want to cancel my order. # 0',
        'Can you help me solve this math problem? # 0',
        'What is a smart contract? # 0',
        'What is a stablecoin? # 0',
        'What is liquidity farming? # 0',
        'What is the current TVL of Uniswap? # 0',
        'How do I buy crypto? # 0',
        'How can I earn yield on my crypto? # 1',
        'What is TVL in DeFi platforms? # 0',
        'How do smart contracts get executed? # 0',
        'Suggest a meme coin trading strategy # 1',
        'How to implement a decentralized exchange? # 1',
        'Is this product still available? # 0',
        'What is your return policy? # 0',
        'Are there any promotions today? # 0',
        'Can you explain the concept of opportunity cost with a real-life example? # 0',
        'Why is emotional intelligence important in the workplace? # 0',
        'What is the difference between correlation and causation? # 0',
        'What are the ethical concerns around artificial intelligence? # 0',
        'What are the differences between a startup and a corporation? # 0',
        'How would you redesign the education system if you could? # 0',
        'How much does it cost? # 0',
        'What’s the weather like today? # 0',
        'I want to invest in a new DeFi project, can you help me? # 1',
        'Recommend high-yield, risk-balanced stablecoin farming strategies # 1',
        'Pick top Raydium AMM v3 LP pools for farming by risk. Analyze all tokens’ data: APR, Volume, Volatility, TVL, Correlation, MA, Bollinger Bands, RSI. Check Impermanent Loss; pick uptrend/neutral tokens with high correlation. Give LP price range, risk strategies, and reasons. Use all data, clear logic. # 0',
        'Search and check stablecoin farming opportunities for a $10,000 investment. The investor wants high yield with balanced risk and is open to any blockchain. # 1',
        'I have $10,000 and want to farm stablecoins with good returns and controlled risk. # 1',
        'Identify trading strategies, assess risks, market trends, and recommend safe short-term trades based on on-chain data and whale behavior in the crypto market. The results should be written in a complete Markdown file, with wallet addresses and a suggested rerun time for the report. # 0',
        'Help me to invest $10,000 into stablecoin farms with good returns and controlled risk. I accept all chains and wants to split the money into different risk levels. You must find and check real pool data like APY, TVL, platform, and asset. Then, organize pools into 3 strategies: low risk, medium risk, and high risk. Give a full list and summary for each. # 0',
        'Suggest Raydium LP pools with full analysis and strategy reasoning. # 1',
        'Analyze the current market trends and suggest a trading strategy for the next week. # 1',
        'How do cross-chain bridges work, and what are the risks associated with them? # 0',
        'How does MEV (Miner Extractable Value / Maximal Extractable Value) impact fairness in DeFi? # 0',
        'How does the EVM (Ethereum Virtual Machine) execute smart contracts securely? # 0',
        'Help me check gas fees on Ethereum right now. # 0',
        'Give me step-by-step instructions to add liquidity on Raydium. # 0',
        'Find a high-APY stablecoin farm for me. # 1',
        'Analyze a farming pool on Raydium and assess its risk level. # 1',
        'Build a farming strategy that auto-balances every week based on yield and TVL shift. # 1',
        'Compare farming performance between Raydium and Orca in the last 14 days. # 1',
        'You are an expert in analyzing whale trading activity in the crypto market. Your task is to identify trading strategies, assess risks, market trends, and recommend safe short-term trades based on on-chain data and whale behavior. The results should be written in a complete Markdown file, with wallet addresses and a suggested rerun time for the report. # 0',
        'You are a trading analyst for the “whales” in the cryptocurrency market, tasked with identifying and analyzing their trading strategies. The goal is to provide analysis that helps traders decide whether to follow the whales’ moves or not. The report should include a risk assessment, 30-day market trends, and suggest safe short-term trades with appropriate entry points, stop losses, and take profits. The report is written in a markdown file and keeps the wallet address intact for verification. Additionally, it is important to determine when it is appropriate to update the report as trades may change. # 0',
        'Search and check stablecoin farming opportunities for a $10,000 investment. The investor wants high yield with balanced risk and is open to any blockchain. # 1',
        'suggest safe short-term trades based on whale trading latest on-chain activity. # 1',
        'Analyze whales and suggest trades. # 1',
        'Track whales and give trading ideas. # 1',
        'Find the best Raydium LP pools # 1',
        'Suggest LP pools on Raydium with strong indicators and explain entry ranges and risk. # 1',
        'Analyze Raydium pools and suggest where to add LP. # 1',
        'Create a stablecoin farming plan by risk level. # 1',
        'Build a stablecoin farming portfolio with real data and safe choices. # 1',
        'Pick top 20 stablecoin farms with verified APY and make an investment strategy. # 1',
        'Create a stablecoin farming strategy with risk levels and real data. # 1',
    ]

    results = []
    incorrect_count = 0

    for prompt_with_label in prompts:
        match = re.match(r'^(.*?)\s*#\s*(\d+)$', prompt_with_label.strip())
        if not match:
            logger.error(f'Invalid prompt format: {prompt_with_label}')
            continue

        prompt, expected_label = match.groups()
        expected_label = int(expected_label)

        # Run test_rewrite and capture full result string
        result = asyncio.run(test_rewrite(prompt))
        output = asyncio.run(test_run(prompt))
        try:
            result_dict = json.loads(result)
            predicted_label = result_dict.get('rewrite', None)
            if predicted_label is None:
                logger.error(f"Invalid result format for prompt '{prompt}': {result}")
                continue

            logger.info(f"Prompt: '{prompt}'")
            logger.info(
                f'Expected rewrite: {expected_label}, Predicted rewrite: {predicted_label}'
            )
            if predicted_label != expected_label:
                incorrect_count += 1
                logger.error(
                    f"Mismatch for prompt '{prompt}': Expected {expected_label}, Got {predicted_label}"
                )
            else:
                logger.info('✓ Correct prediction')

            results.append(
                {
                    'Prompt': prompt,
                    'Ground Truth': expected_label,
                    'AI Predict': predicted_label,
                    'Optimized Prompt': output,
                }
            )

        except json.JSONDecodeError:
            logger.error(
                f"Failed to parse result as JSON for prompt '{prompt}': {result}"
            )
            results.append(
                {
                    'Prompt': prompt,
                    'Ground Truth': expected_label,
                    'AI Predict': 'Error',
                    'Optimized Prompt': output,  # Save raw output even if it's not JSON
                }
            )
            continue

    # Write results to CSV
    csv_file = 'prompt_evaluation_results.csv'
    with open(csv_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(
            file,
            fieldnames=['Prompt', 'Ground Truth', 'AI Predict', 'Optimized Prompt'],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(result)
    logger.info(f'Results saved to {csv_file}')

    logger.info(f'\nTotal number of incorrect predictions: {incorrect_count}')
    logger.info(f'Total prompts processed: {len(prompts)}')
    logger.info(
        f'Accuracy: {100 * (len(prompts) - incorrect_count) / len(prompts):.2f}%'
    )


# Run the batch
run_batch()
