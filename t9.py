# Copyright 2021 Optiver Asia Pacific Pty. Ltd.
#
# This file is part of Ready Trader One.
#
#     Ready Trader One is free software: you can redistribute it and/or
#     modify it under the terms of the GNU Affero General Public License
#     as published by the Free Software Foundation, either version 3 of
#     the License, or (at your option) any later version.
#
#     Ready Trader One is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public
#     License along with Ready Trader One.  If not, see
#     <https://www.gnu.org/licenses/>.
import asyncio
import numpy
import itertools

from typing import List

from ready_trader_one import BaseAutoTrader, Instrument, Lifespan, Side

LOT_SIZE = 10
POSITION_LIMIT = 1000
TICK_SIZE_IN_CENTS = 100
MAX_LOT_SIZE = 10
SHAPE_PARAMETER = -0.09
WAIT_TIME = 1
S_VALUE_LIST = []
S_VALUE = 3400  ## Midpoint???
GAMMA = 0.075
STD_DEV = 2  ## std dev of midpoint???
T_FINAL = 3600
K_VALUE = 0.1


class AutoTrader(BaseAutoTrader):
    """Example Auto-trader.

    When it starts this auto-trader places ten-lot bid and ask orders at the
    current best-bid and best-ask prices respectively. Thereafter, if it has
    a long position (it has bought more lots than it has sold) it reduces its
    bid and ask prices. Conversely, if it has a short position (it has sold
    more lots than it has bought) then it increases its bid and ask prices.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, team_name: str, secret: str):
        """Initialise a new instance of the AutoTrader class."""
        super().__init__(loop, team_name, secret)
        self.order_ids = itertools.count(1)
        self.bids = set()
        self.asks = set()
        self.ask_id = self.ask_price = self.bid_id = self.bid_price = self.position = 0
        self.no_orders = 0
        self.current_time = self.bid_time = self.ask_time = 0
        self.ask_count = self.bid_count = -1
        self.s_value_list = []
        self.s_value = 0
        self.std_dev = 0
        self.spread = 0
        self.previous_midpoint = 0

    def on_error_message(self, client_order_id: int, error_message: bytes) -> None:
        """Called when the exchange detects an error.

        If the error pertains to a particular order, then the client_order_id
        will identify that order, otherwise the client_order_id will be zero.
        """
        self.logger.warning("error with order %d: %s", client_order_id, error_message.decode())
        if client_order_id != 0:
            self.on_order_status_message(client_order_id, 0, 0, 0)

    def order_size(self) -> (int, int):
        """

        :return:
        """

        ask_order = bid_order = MAX_LOT_SIZE
        if 0 > self.position > -POSITION_LIMIT:
            bid_order = MAX_LOT_SIZE
            ask_order = MAX_LOT_SIZE * numpy.exp(-SHAPE_PARAMETER * self.position)
        elif 0 < self.position < POSITION_LIMIT:
            ask_order = MAX_LOT_SIZE
            bid_order = MAX_LOT_SIZE * numpy.exp(SHAPE_PARAMETER * self.position)

        bid_order = round(bid_order)
        ask_order = round(ask_order)

        bid_order = min(bid_order, MAX_LOT_SIZE)
        ask_order = min(ask_order, MAX_LOT_SIZE)
        return bid_order, ask_order

    def bid_ask_quote(self) -> (int, int):
        indifference = self.indifference_price()
        spread = self.spread()
        #print("Indifference: " + str(indifference) + " spread: " + str(spread) + " std dev: " + str(self.std_dev))
        return round(indifference - spread) * TICK_SIZE_IN_CENTS, round(indifference + spread) * TICK_SIZE_IN_CENTS

    def insert_order(self, bid_order: bool, volume: int):
        if bid_order:
            self.bid_id = next(self.order_ids)
            print("bid price: " + str(self.bid_price))
            self.send_insert_order(self.bid_id, Side.BUY, (int(self.bid_price) // TICK_SIZE_IN_CENTS) * TICK_SIZE_IN_CENTS, volume, Lifespan.GOOD_FOR_DAY)
            self.bids.add(self.bid_id)
            self.bid_time = self.current_time
        else:
            self.ask_id = next(self.order_ids)
            print("sell price: " + str(self.ask_price))
            self.send_insert_order(self.ask_id, Side.ASK, (int(self.ask_price)// TICK_SIZE_IN_CENTS) * TICK_SIZE_IN_CENTS, volume, Lifespan.GOOD_FOR_DAY)
            self.asks.add(self.ask_id)
            self.ask_time = self.current_time
        self.no_orders += 1

    def cancel_order(self, bid_order: bool):
        if bid_order:
            self.send_cancel_order(self.bid_id)
            self.bid_time = 0
            self.bid_id = 0
        else:
            self.send_cancel_order(self.ask_id)
            self.ask_time = 0
            self.ask_id = 0
        self.no_orders -= 1

    # def order_policy(self):

    def indifference_price(self):
        # print("s value: " + str(self.s_value) + " position: " + str(self.position))
        return self.s_value
               #- self.position * self.std_dev * self.std_dev * (1 - self.current_time * 0.00003)

    def spread(self):
        return self.std_dev * self.std_dev * (1 - self.current_time * 0.00003)

    def on_order_book_update_message(self, instrument: int, sequence_number: int, ask_prices: List[int],
                                     ask_volumes: List[int], bid_prices: List[int], bid_volumes: List[int]) -> None:
        """Called periodically to report the status of an order book.

        The sequence number can be used to detect missed or out-of-order
        messages. The five best available ask (i.e. sell) and bid (i.e. buy)
        prices are reported along with the volume available at each of those
        price levels.
        """
        if instrument == Instrument.FUTURE:
            current_midprice = (bid_prices[0] + ask_prices[0]) / 2
            current_midprice = (current_midprice // TICK_SIZE_IN_CENTS)
            self.s_value = current_midprice

            if len(self.s_value_list) < 5 and current_midprice != 0:
                self.s_value_list.append(current_midprice)
            elif current_midprice != 0:
                del self.s_value_list[0]
                self.s_value_list.append(current_midprice)

            self.spread = abs(bid_prices[0] - ask_prices[0])
            self.spread = (self.spread // TICK_SIZE_IN_CENTS) / 2
            #print(self.spread)

            delta_p = 0

            if len(self.s_value_list) == 5:
                delta_p = (self.s_value_list[-1] - self.s_value_list[0]) / 5



            s_sum = 0
            for s in self.s_value_list:
                s_sum = s_sum + s
            # print("s sum: " + str(s_sum) + " length: " + str(len(self.s_value_list)))
            #if len(self.s_value_list) != 0:
               # self.s_value = (s_sum / len(self.s_value_list))

            bid_volume, ask_volume = self.order_size()
            # print("no orders: " + str(self.no_orders) + " bid id: " + str(self.bid_id) + " ask id: " + str(self.ask_id))
            # print("current time: " + str(self.current_time) + " ask time: " + str(self.ask_time))
            if self.no_orders == 0:
                #self.bid_price, self.ask_price = self.bid_ask_quote()
                self.bid_price = bid_prices[0] + delta_p
                self.ask_price = ask_prices[0] + delta_p
                print("bid price: " + str(self.bid_price) + " ask price: " + str(self.ask_price))
                if self.bid_price != self.ask_price:
                    self.insert_order(True, bid_volume)
                    self.insert_order(False, ask_volume)

            elif self.no_orders == 1:
                if self.bid_id != 0:
                    if (self.current_time - self.bid_time) > WAIT_TIME:
                        self.cancel_order(True)
                        self.bid_price = bid_prices[0] + delta_p
                        self.ask_price = ask_prices[0] + delta_p
                        print("bid price: " + str(self.bid_price) + " ask price: " + str(self.ask_price))
                        if self.bid_price != self.ask_price:
                            self.insert_order(True, bid_volume)
                            self.insert_order(False, ask_volume)
                elif self.ask_id != 0:
                    if (self.current_time - self.ask_time) > WAIT_TIME:
                        self.cancel_order(False)
                        self.bid_price = bid_prices[0] + delta_p
                        self.ask_price = ask_prices[0] + delta_p
                        if self.bid_price != self.ask_price:
                            self.insert_order(True, bid_volume)
                            self.insert_order(False, ask_volume)
            elif self.no_orders == 2:
                if (self.current_time - self.bid_time) > WAIT_TIME:
                    self.cancel_order(True)
                    self.cancel_order(False)
                    self.bid_price = bid_prices[0] + delta_p
                    self.ask_price = ask_prices[0] + delta_p
                    if self.bid_price != self.ask_price:
                        self.insert_order(True, bid_volume)
                        self.insert_order(False, ask_volume)

        self.current_time += 1

    def on_order_filled_message(self, client_order_id: int, price: int, volume: int) -> None:
        """Called when when of your orders is filled, partially or fully.

        The price is the price at which the order was (partially) filled,
        which may be better than the order's limit price. The volume is
        the number of lots filled at that price.
        """
        if client_order_id in self.bids:
            self.position += volume
        elif client_order_id in self.asks:
            self.position -= volume

    def on_trade_ticks_message(self, instrument: int, sequence_number: int, ask_prices: List[int],
                               ask_volumes: List[int], bid_prices: List[int], bid_volumes: List[int]) -> None:
        """Called when there is trading activity on the market.

        The five best ask (i.e. sell) and bid (i.e. buy) prices at which there
        has been trading activity are reported along with the volume traded at
        each of those price levels. If there are less than five prices on a
        side, then zeros will appear at the end of both the prices and volumes
        lists on that side so that there are always five entries in each list.
        """
        pass

    def on_order_status_message(self, client_order_id: int, fill_volume: int, remaining_volume: int,
                                fees: int) -> None:
        """Called when the status of one of your orders changes.

        The fill_volume is the number of lots already traded, remaining_volume
        is the number of lots yet to be traded and fees is the total fees for
        this order. Remember that you pay fees for being a market taker, but
        you receive fees for being a market maker, so fees can be negative.

        If an order is cancelled its remaining volume will be zero.
        """
        if remaining_volume == 0:
            if client_order_id == self.bid_id:
                self.bid_id = 0
                self.no_orders -= 1
            elif client_order_id == self.ask_id:
                self.ask_id = 0
                self.no_orders -= 1

            # It could be either a bid or an ask
            self.bids.discard(client_order_id)
            self.asks.discard(client_order_id)
