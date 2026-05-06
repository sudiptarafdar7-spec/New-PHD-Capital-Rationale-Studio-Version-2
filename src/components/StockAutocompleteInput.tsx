import React, { useState, useEffect, useRef } from 'react';
import { Command, CommandGroup, CommandItem, CommandList } from './ui/command';
import { Input } from './ui/input';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { Check, Loader2 } from 'lucide-react';

export interface Stock {
  name: string;
  symbol: string;
  securityId: string;
  exchange: string;
  listedName: string;
  shortName: string;
  instrument: string;
}

interface StockAutocompleteInputProps {
  value: string;
  onSelect: (stock: Stock | null, stockSymbol: string) => void;
  token: string;
  placeholder?: string;
  disabled?: boolean;
  useV2Api?: boolean;
}

export function StockAutocompleteInput({
  value,
  onSelect,
  token,
  placeholder = 'Type to search stocks...',
  disabled = false,
  useV2Api = false,
}: StockAutocompleteInputProps) {
  const [open, setOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const [suggestions, setSuggestions] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(false);
  const [debouncedValue, setDebouncedValue] = useState(inputValue);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Debounce input value
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(inputValue);
    }, 300);

    return () => clearTimeout(timer);
  }, [inputValue]);

  // Fetch suggestions when debounced value changes
  useEffect(() => {
    if (!debouncedValue || debouncedValue.length < 2) {
      setSuggestions([]);
      return;
    }

    const fetchSuggestions = async () => {
      // Cancel previous request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      // Create new abort controller
      abortControllerRef.current = new AbortController();

      setLoading(true);

      try {
        const endpoint = useV2Api 
          ? API_ENDPOINTS.manualV2.stocks(debouncedValue)
          : API_ENDPOINTS.uploadedFiles.masterStocks(debouncedValue);
        
        const response = await fetch(endpoint, {
          headers: getAuthHeaders(token),
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error('Failed to fetch stocks');
        }

        const data = await response.json();
        setSuggestions(data.stocks || []);
      } catch (error: any) {
        if (error.name !== 'AbortError') {
          console.error('Error fetching stock suggestions:', error);
          setSuggestions([]);
        }
      } finally {
        setLoading(false);
      }
    };

    fetchSuggestions();

    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [debouncedValue, token]);

  // Sync external value changes
  useEffect(() => {
    setInputValue(value);
  }, [value]);

  const handleSelect = (stock: Stock) => {
    setInputValue(stock.symbol);
    onSelect(stock, stock.symbol);
    setOpen(false);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value;
    setInputValue(newValue);
    onSelect(null, newValue); // Update parent state immediately with null stock data
    
    if (newValue.length >= 2) {
      setOpen(true);
    } else {
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      <Input
        value={inputValue}
        onChange={handleInputChange}
        onFocus={() => {
          if (inputValue.length >= 2 && suggestions.length > 0) {
            setOpen(true);
          }
        }}
        onBlur={() => {
          // Delay closing to allow click on suggestions
          setTimeout(() => setOpen(false), 200);
        }}
        placeholder={placeholder}
        disabled={disabled}
        className="bg-background border-input"
      />
      {loading && (
        <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground animate-spin" />
      )}
      {open && suggestions.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-popover border border-border rounded-md shadow-md max-h-[300px] overflow-auto">
          <Command>
            <CommandList>
              <CommandGroup>
                {suggestions.map((stock, index) => (
                  <CommandItem
                    key={`${stock.securityId}-${index}`}
                    value={stock.symbol}
                    onMouseDown={(e) => {
                      e.preventDefault(); // Prevent blur
                      handleSelect(stock);
                    }}
                    className="cursor-pointer"
                  >
                    <div className="flex items-center justify-between w-full">
                      <div className="flex flex-col">
                        <span className="font-medium">{stock.symbol}</span>
                        <span className="text-xs text-muted-foreground">
                          {stock.name} • {stock.exchange}
                        </span>
                      </div>
                      {inputValue === stock.symbol && (
                        <Check className="w-4 h-4 text-primary" />
                      )}
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </div>
      )}
      {open && suggestions.length === 0 && !loading && debouncedValue.length >= 2 && (
        <div className="absolute z-50 w-full mt-1 bg-popover border border-border rounded-md shadow-md p-2">
          <p className="text-sm text-muted-foreground text-center">No EQUITY stocks found</p>
        </div>
      )}
    </div>
  );
}
